from flask import Flask, render_template, request, jsonify, send_file, g
from flask_cors import CORS
import sqlite3
import os
import uuid
import re
from datetime import datetime, timedelta
import csv
import io

app = Flask(__name__)
CORS(app, allow_headers=['Content-Type', 'X-Household-Id'], expose_headers=['Content-Type'])
app.config['SECRET_KEY'] = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')

DATABASE = os.environ.get('DATABASE', 'kakeibo.db')

LEGACY_HOUSEHOLD_ID = '00000000-0000-4000-8000-000000000001'
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', re.I)


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn, table):
    cur = conn.execute(f'PRAGMA table_info({table})')
    return [row[1] for row in cur.fetchall()]


def migrate_schema(conn):
    if 'household_id' in _table_columns(conn, 'transactions'):
        return

    conn.execute('''
        CREATE TABLE IF NOT EXISTS households (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.execute('INSERT OR IGNORE INTO households (id) VALUES (?)', (LEGACY_HOUSEHOLD_ID,))

    conn.execute('ALTER TABLE transactions ADD COLUMN household_id TEXT')
    conn.execute('UPDATE transactions SET household_id = ? WHERE household_id IS NULL', (LEGACY_HOUSEHOLD_ID,))

    conn.execute('''
        CREATE TABLE categories_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            household_id TEXT NOT NULL,
            name TEXT NOT NULL,
            icon TEXT,
            type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(household_id, name)
        )
    ''')
    conn.execute('''
        INSERT INTO categories_new (id, household_id, name, icon, type, created_at)
        SELECT id, ?, name, icon, type, created_at FROM categories
    ''', (LEGACY_HOUSEHOLD_ID,))
    conn.execute('DROP TABLE categories')
    conn.execute('ALTER TABLE categories_new RENAME TO categories')

    conn.execute('''
        CREATE TABLE settings_new (
            household_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (household_id, key)
        )
    ''')
    conn.execute('''
        INSERT INTO settings_new (household_id, key, value)
        SELECT ?, key, value FROM settings
    ''', (LEGACY_HOUSEHOLD_ID,))
    conn.execute('DROP TABLE settings')
    conn.execute('ALTER TABLE settings_new RENAME TO settings')


def init_db():
    conn = get_db_connection()

    conn.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT NOT NULL,
            amount INTEGER NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            icon TEXT,
            type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    migrate_schema(conn)

    existing_categories = conn.execute('SELECT COUNT(*) as count FROM categories').fetchone()['count']
    if existing_categories == 0:
        default_categories = [
            ('cat_salary', '💰', 'income'),
            ('cat_bonus', '🎁', 'income'),
            ('cat_other_income', '📥', 'income'),
            ('cat_food', '🍔', 'expense'),
            ('cat_transportation', '🚗', 'expense'),
            ('cat_housing', '🏠', 'expense'),
            ('cat_utilities', '💡', 'expense'),
            ('cat_communication', '📱', 'expense'),
            ('cat_entertainment', '🎮', 'expense'),
            ('cat_medical', '🏥', 'expense'),
            ('cat_other', '📦', 'expense')
        ]
        conn.executemany(
            'INSERT INTO categories (household_id, name, icon, type) VALUES (?, ?, ?, ?)',
            [(LEGACY_HOUSEHOLD_ID, n, i, t) for n, i, t in default_categories]
        )

    existing_settings = conn.execute('SELECT COUNT(*) as count FROM settings').fetchone()['count']
    if existing_settings == 0:
        default_settings = [
            ('period_start_day', '1'),
            ('currency', 'JPY'),
            ('language', 'ja')
        ]
        conn.executemany(
            'INSERT INTO settings (household_id, key, value) VALUES (?, ?, ?)',
            [(LEGACY_HOUSEHOLD_ID, k, v) for k, v in default_settings]
        )

    conn.commit()
    conn.close()


def seed_household_defaults(conn, hid):
    default_categories = [
        ('cat_salary', '💰', 'income'),
        ('cat_bonus', '🎁', 'income'),
        ('cat_other_income', '📥', 'income'),
        ('cat_food', '🍔', 'expense'),
        ('cat_transportation', '🚗', 'expense'),
        ('cat_housing', '🏠', 'expense'),
        ('cat_utilities', '💡', 'expense'),
        ('cat_communication', '📱', 'expense'),
        ('cat_entertainment', '🎮', 'expense'),
        ('cat_medical', '🏥', 'expense'),
        ('cat_other', '📦', 'expense')
    ]
    conn.executemany(
        'INSERT INTO categories (household_id, name, icon, type) VALUES (?, ?, ?, ?)',
        [(hid, n, i, t) for n, i, t in default_categories]
    )
    default_settings = [
        ('period_start_day', '1'),
        ('currency', 'JPY'),
        ('language', 'ja')
    ]
    conn.executemany(
        'INSERT INTO settings (household_id, key, value) VALUES (?, ?, ?)',
        [(hid, k, v) for k, v in default_settings]
    )


with app.app_context():
    init_db()


@app.before_request
def attach_household():
    if not request.path.startswith('/api/'):
        return
    if request.method == 'OPTIONS':
        return
    if request.path == '/api/households' and request.method == 'POST':
        return
    hid = request.headers.get('X-Household-Id', '').strip()
    if not hid or not UUID_RE.match(hid):
        return jsonify({'error_key': 'household_required'}), 401
    conn = get_db_connection()
    row = conn.execute('SELECT 1 FROM households WHERE id = ?', (hid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error_key': 'household_not_found'}), 404
    g.household_id = hid


@app.route('/')
def index():
    return render_template('index.html')


def get_period_start_day():
    conn = get_db_connection()
    result = conn.execute(
        'SELECT value FROM settings WHERE household_id = ? AND key = ?',
        (g.household_id, 'period_start_day')
    ).fetchone()
    conn.close()
    return int(result['value']) if result else 1


def calculate_period_dates(year, month, start_day):
    from calendar import monthrange

    year = int(year)
    month = int(month)

    period_start = datetime(year, month, min(start_day, monthrange(year, month)[1]))

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    period_end_date = datetime(next_year, next_month, min(start_day, monthrange(next_year, next_month)[1]))
    period_end = period_end_date - timedelta(days=1)

    return period_start.strftime('%Y-%m-%d'), period_end.strftime('%Y-%m-%d')


@app.route('/api/households', methods=['POST'])
def create_household():
    hid = str(uuid.uuid4())
    conn = get_db_connection()
    conn.execute('INSERT INTO households (id) VALUES (?)', (hid,))
    seed_household_defaults(conn, hid)
    conn.commit()
    conn.close()
    return jsonify({'id': hid})


@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    conn = get_db_connection()
    year = request.args.get('year')
    month = request.args.get('month')

    query = 'SELECT * FROM transactions WHERE household_id = ?'
    params = [g.household_id]

    if year and month:
        start_day = get_period_start_day()
        start_date, end_date = calculate_period_dates(year, month, start_day)
        query += ' AND date >= ? AND date <= ?'
        params.extend([start_date, end_date])
    elif year:
        start_day = get_period_start_day()
        start_date, _ = calculate_period_dates(year, '1', start_day)
        _, end_date = calculate_period_dates(year, '12', start_day)
        query += ' AND date >= ? AND date <= ?'
        params.extend([start_date, end_date])

    query += ' ORDER BY date DESC, id DESC'

    transactions = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(row) for row in transactions])


@app.route('/api/transactions', methods=['POST'])
def add_transaction():
    data = request.json

    if not all(k in data for k in ['date', 'type', 'category', 'amount']):
        return jsonify({'error_key': 'required_fields'}), 400

    conn = get_db_connection()
    conn.execute(
        'INSERT INTO transactions (household_id, date, type, category, amount, description) VALUES (?, ?, ?, ?, ?, ?)',
        (g.household_id, data['date'], data['type'], data['category'], int(data['amount']), data.get('description', ''))
    )
    conn.commit()
    conn.close()

    return jsonify({'success': True})


@app.route('/api/transactions/<int:id>', methods=['PUT'])
def update_transaction(id):
    data = request.json

    if not all(k in data for k in ['date', 'type', 'category', 'amount']):
        return jsonify({'error_key': 'required_fields'}), 400

    conn = get_db_connection()
    cur = conn.execute(
        'UPDATE transactions SET date = ?, type = ?, category = ?, amount = ?, description = ? WHERE id = ? AND household_id = ?',
        (data['date'], data['type'], data['category'], int(data['amount']), data.get('description', ''), id, g.household_id)
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({'error_key': 'not_found'}), 404

    return jsonify({'success': True})


@app.route('/api/transactions/<int:id>', methods=['DELETE'])
def delete_transaction(id):
    conn = get_db_connection()
    cur = conn.execute('DELETE FROM transactions WHERE id = ? AND household_id = ?', (id, g.household_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({'error_key': 'not_found'}), 404
    return jsonify({'success': True})


@app.route('/api/summary', methods=['GET'])
def get_summary():
    conn = get_db_connection()
    year = request.args.get('year')
    month = request.args.get('month')

    query_params = [g.household_id]
    where_clause = 'household_id = ?'

    if year and month:
        start_day = get_period_start_day()
        start_date, end_date = calculate_period_dates(year, month, start_day)
        where_clause += ' AND date >= ? AND date <= ?'
        query_params.extend([start_date, end_date])
    elif year:
        start_day = get_period_start_day()
        start_date, _ = calculate_period_dates(year, '1', start_day)
        _, end_date = calculate_period_dates(year, '12', start_day)
        where_clause += ' AND date >= ? AND date <= ?'
        query_params.extend([start_date, end_date])

    income = conn.execute(
        f'SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE type = "income" AND {where_clause}',
        query_params
    ).fetchone()['total']

    expense = conn.execute(
        f'SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE type = "expense" AND {where_clause}',
        query_params
    ).fetchone()['total']

    category_summary = conn.execute(
        f'SELECT category, SUM(amount) as total FROM transactions WHERE type = "expense" AND {where_clause} GROUP BY category',
        query_params
    ).fetchall()

    conn.close()

    return jsonify({
        'income': income,
        'expense': expense,
        'balance': income - expense,
        'categories': [dict(row) for row in category_summary]
    })


@app.route('/api/categories', methods=['GET'])
def get_categories():
    conn = get_db_connection()
    category_type = request.args.get('type')

    if category_type:
        categories = conn.execute(
            'SELECT * FROM categories WHERE household_id = ? AND type = ? ORDER BY name',
            (g.household_id, category_type)
        ).fetchall()
    else:
        categories = conn.execute(
            'SELECT * FROM categories WHERE household_id = ? ORDER BY type, name',
            (g.household_id,)
        ).fetchall()

    conn.close()
    return jsonify([dict(row) for row in categories])


@app.route('/api/categories', methods=['POST'])
def add_category():
    data = request.json

    if not all(k in data for k in ['name', 'type']):
        return jsonify({'error_key': 'required_fields'}), 400

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO categories (household_id, name, icon, type) VALUES (?, ?, ?, ?)',
            (g.household_id, data['name'], data.get('icon', '📦'), data['type'])
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error_key': 'duplicate_category'}), 400


@app.route('/api/categories/<int:id>', methods=['PUT'])
def update_category(id):
    data = request.json

    if not all(k in data for k in ['name', 'type']):
        return jsonify({'error_key': 'required_fields'}), 400

    conn = get_db_connection()
    try:
        cur = conn.execute(
            'UPDATE categories SET name = ?, icon = ?, type = ? WHERE id = ? AND household_id = ?',
            (data['name'], data.get('icon', '📦'), data['type'], id, g.household_id)
        )
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            return jsonify({'error_key': 'not_found'}), 404
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error_key': 'duplicate_category'}), 400


@app.route('/api/categories/<int:id>', methods=['DELETE'])
def delete_category(id):
    conn = get_db_connection()
    cur = conn.execute('DELETE FROM categories WHERE id = ? AND household_id = ?', (id, g.household_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({'error_key': 'not_found'}), 404
    return jsonify({'success': True})


@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db_connection()
    settings = conn.execute(
        'SELECT key, value FROM settings WHERE household_id = ?',
        (g.household_id,)
    ).fetchall()
    conn.close()

    result = {}
    for setting in settings:
        result[setting['key']] = setting['value']

    return jsonify(result)


@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.json or {}
    allowed = {'currency', 'language', 'period_start_day'}
    conn = get_db_connection()
    for key, raw in data.items():
        if key not in allowed:
            continue
        value = str(raw).strip() if raw is not None else ''
        if key == 'period_start_day':
            try:
                d = int(value)
            except (TypeError, ValueError):
                continue
            if d < 1 or d > 31:
                continue
            value = str(d)
        conn.execute(
            'INSERT OR REPLACE INTO settings (household_id, key, value) VALUES (?, ?, ?)',
            (g.household_id, key, value)
        )
    conn.commit()
    conn.close()

    return jsonify({'success': True})


@app.route('/api/export', methods=['GET'])
def export_csv():
    conn = get_db_connection()
    transactions = conn.execute(
        'SELECT * FROM transactions WHERE household_id = ? ORDER BY date DESC',
        (g.household_id,)
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['日付', '種類', 'カテゴリ', '金額', '説明'])

    for t in transactions:
        type_text = '収入' if t['type'] == 'income' else '支出'
        writer.writerow([t['date'], type_text, t['category'], t['amount'], t['description']])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'kakeibo_{datetime.now().strftime("%Y%m%d")}.csv'
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
