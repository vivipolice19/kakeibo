from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime, timedelta
import csv
import io
import json

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')

DATABASE = os.environ.get('DATABASE', 'kakeibo.db')

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

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
        conn.executemany('INSERT INTO categories (name, icon, type) VALUES (?, ?, ?)', default_categories)
    
    existing_settings = conn.execute('SELECT COUNT(*) as count FROM settings').fetchone()['count']
    if existing_settings == 0:
        default_settings = [
            ('period_start_day', '1'),
            ('currency', 'JPY'),
            ('language', 'ja')
        ]
        conn.executemany('INSERT INTO settings (key, value) VALUES (?, ?)', default_settings)
    
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

@app.route('/')
def index():
    return render_template('index.html')

def get_period_start_day():
    conn = get_db_connection()
    result = conn.execute('SELECT value FROM settings WHERE key = ?', ('period_start_day',)).fetchone()
    conn.close()
    return int(result['value']) if result else 1

def calculate_period_dates(year, month, start_day):
    from datetime import datetime, timedelta
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

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    conn = get_db_connection()
    year = request.args.get('year')
    month = request.args.get('month')
    
    query = 'SELECT * FROM transactions'
    params = []
    
    if year and month:
        start_day = get_period_start_day()
        start_date, end_date = calculate_period_dates(year, month, start_day)
        query += ' WHERE date >= ? AND date <= ?'
        params = [start_date, end_date]
    elif year:
        start_day = get_period_start_day()
        year_int = int(year)
        start_date, _ = calculate_period_dates(year, '1', start_day)
        _, end_date = calculate_period_dates(year, '12', start_day)
        query += ' WHERE date >= ? AND date <= ?'
        params = [start_date, end_date]
    
    query += ' ORDER BY date DESC, id DESC'
    
    transactions = conn.execute(query, params).fetchall()
    conn.close()
    
    return jsonify([dict(row) for row in transactions])

@app.route('/api/transactions', methods=['POST'])
def add_transaction():
    data = request.json
    
    if not all(k in data for k in ['date', 'type', 'category', 'amount']):
        return jsonify({'error': '必須項目が不足しています'}), 400
    
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO transactions (date, type, category, amount, description) VALUES (?, ?, ?, ?, ?)',
        (data['date'], data['type'], data['category'], int(data['amount']), data.get('description', ''))
    )
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/transactions/<int:id>', methods=['PUT'])
def update_transaction(id):
    data = request.json
    
    if not all(k in data for k in ['date', 'type', 'category', 'amount']):
        return jsonify({'error': '必須項目が不足しています'}), 400
    
    conn = get_db_connection()
    conn.execute(
        'UPDATE transactions SET date = ?, type = ?, category = ?, amount = ?, description = ? WHERE id = ?',
        (data['date'], data['type'], data['category'], int(data['amount']), data.get('description', ''), id)
    )
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/transactions/<int:id>', methods=['DELETE'])
def delete_transaction(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM transactions WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/summary', methods=['GET'])
def get_summary():
    conn = get_db_connection()
    year = request.args.get('year')
    month = request.args.get('month')
    
    query_params = []
    where_clause = ''
    
    if year and month:
        start_day = get_period_start_day()
        start_date, end_date = calculate_period_dates(year, month, start_day)
        where_clause = ' AND date >= ? AND date <= ?'
        query_params = [start_date, end_date]
    elif year:
        start_day = get_period_start_day()
        start_date, _ = calculate_period_dates(year, '1', start_day)
        _, end_date = calculate_period_dates(year, '12', start_day)
        where_clause = ' AND date >= ? AND date <= ?'
        query_params = [start_date, end_date]
    
    income = conn.execute(
        f'SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE type = "income"{where_clause}',
        query_params
    ).fetchone()['total']
    
    expense = conn.execute(
        f'SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE type = "expense"{where_clause}',
        query_params
    ).fetchone()['total']
    
    category_summary = conn.execute(
        f'SELECT category, SUM(amount) as total FROM transactions WHERE type = "expense"{where_clause} GROUP BY category',
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
        categories = conn.execute('SELECT * FROM categories WHERE type = ? ORDER BY name', (category_type,)).fetchall()
    else:
        categories = conn.execute('SELECT * FROM categories ORDER BY type, name').fetchall()
    
    conn.close()
    return jsonify([dict(row) for row in categories])

@app.route('/api/categories', methods=['POST'])
def add_category():
    data = request.json
    
    if not all(k in data for k in ['name', 'type']):
        return jsonify({'error': '必須項目が不足しています'}), 400
    
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO categories (name, icon, type) VALUES (?, ?, ?)',
            (data['name'], data.get('icon', '📦'), data['type'])
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'このカテゴリ名は既に存在します'}), 400

@app.route('/api/categories/<int:id>', methods=['PUT'])
def update_category(id):
    data = request.json
    
    if not all(k in data for k in ['name', 'type']):
        return jsonify({'error': '必須項目が不足しています'}), 400
    
    conn = get_db_connection()
    try:
        conn.execute(
            'UPDATE categories SET name = ?, icon = ?, type = ? WHERE id = ?',
            (data['name'], data.get('icon', '📦'), data['type'], id)
        )
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'このカテゴリ名は既に存在します'}), 400

@app.route('/api/categories/<int:id>', methods=['DELETE'])
def delete_category(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM categories WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db_connection()
    settings = conn.execute('SELECT * FROM settings').fetchall()
    conn.close()
    
    result = {}
    for setting in settings:
        result[setting['key']] = setting['value']
    
    return jsonify(result)

@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.json
    
    conn = get_db_connection()
    for key, value in data.items():
        conn.execute(
            'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
            (key, value)
        )
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/export', methods=['GET'])
def export_csv():
    conn = get_db_connection()
    transactions = conn.execute('SELECT * FROM transactions ORDER BY date DESC').fetchall()
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
