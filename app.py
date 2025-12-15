import os
import sqlite3
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-change-me'

DB_PATH = os.path.join(os.path.dirname(__file__), 'kashidashi1215.db')


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_openbd(isbn: str):
    """Fetch book metadata from OpenBD. Returns dict with keys 'title' and 'text' or None if not found."""
    try:
        url = f'https://api.openbd.jp/v1/get?isbn={isbn}'
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data or data[0] is None:
            return None
        item = data[0]

        # Try summary-based title first
        title = None
        if isinstance(item, dict):
            summary = item.get('summary') or {}
            title = summary.get('title') if isinstance(summary, dict) else None

        # Try to extract ONIX TitleText
        if not title:
            onix = item.get('onix', {}) if isinstance(item, dict) else {}
            dd = onix.get('DescriptiveDetail', {})
            td = dd.get('TitleDetail')
            def extract_title(td):
                if not td:
                    return None
                if isinstance(td, list):
                    els = td
                else:
                    els = [td]
                for e in els:
                    te = e.get('TitleElement')
                    if not te:
                        continue
                    te_list = te if isinstance(te, list) else [te]
                    for t in te_list:
                        tt = t.get('TitleText')
                        if tt:
                            if isinstance(tt, dict):
                                c = tt.get('content') or tt.get('Text')
                                if c:
                                    return c
                            else:
                                return str(tt)
                return None
            title = extract_title(td)

        # Text content (summary or CollateralDetail.TextContent)
        text_parts = []
        if isinstance(item, dict):
            # summary.description may exist
            if isinstance(item.get('summary'), dict):
                s = item['summary'].get('description') or item['summary'].get('content')
                if s:
                    text_parts.append(s)

            onix = item.get('onix') or {}
            coll = onix.get('CollateralDetail', {}).get('TextContent', [])
            if coll and not isinstance(coll, list):
                coll = [coll]
            for tc in coll or []:
                # tc may contain 'Text' key or 'TextContent' structure
                t = None
                if isinstance(tc, dict):
                    if 'Text' in tc:
                        tv = tc.get('Text')
                        if isinstance(tv, dict):
                            t = tv.get('content') or tv.get('Text')
                        else:
                            t = str(tv)
                    else:
                        # sometimes Text is nested differently
                        t = tc.get('TextContent') or tc.get('content')
                if t:
                    text_parts.append(t)

        text = '\n\n'.join(text_parts).strip() if text_parts else None
        # Subjects (try to extract subject code / heading from ONIX)
        subjects = []
        try:
            onix = item.get('onix') or {}
            subj = onix.get('DescriptiveDetail', {}).get('Subject', [])
            if subj and not isinstance(subj, list):
                subj = [subj]
            for s in subj or []:
                if not isinstance(s, dict):
                    continue
                # Prefer code fields
                code = s.get('SubjectCode') or s.get('SubjectCodeValue') or s.get('Code')
                if code:
                    subjects.append(str(code))
                    continue
                # Try heading/text
                heading = s.get('SubjectHeadingText') or s.get('Text') or s.get('SubjectHeading')
                if heading:
                    subjects.append(str(heading))
        except Exception:
            subjects = []

        return {'title': title, 'text': text, 'subjects': subjects}
    except Exception:
        return None


@app.route('/')
def index():
    conn = get_db_connection()
    users = conn.execute('SELECT user_id, name FROM USERS ORDER BY name').fetchall()
    books = conn.execute('SELECT isbn, title FROM BOOKS ORDER BY title').fetchall()
    actions = conn.execute('SELECT action_id, action_name FROM ACTIONS ORDER BY action_id').fetchall()
    logs = conn.execute(
        '''
        SELECT L.loan_id, L.logged_at, U.name as user_name, B.title as book_title, B.isbn, A.action_name
        FROM LOAN_LOGS L
        LEFT JOIN USERS U ON L.user_id = U.user_id
        LEFT JOIN BOOKS B ON L.isbn = B.isbn
        LEFT JOIN ACTIONS A ON L.action_id = A.action_id
        ORDER BY L.logged_at DESC
        LIMIT 20
        '''
    ).fetchall()
    conn.close()
    return render_template('index.html', users=users, books=books, actions=actions, logs=logs)


@app.route('/current_loans')
def current_loans():
        """Show currently loaned books: for each ISBN take the latest LOAN_LOGS entry and
        display those whose action is '貸し出し'."""
        conn = get_db_connection()
        rows = conn.execute(
                '''
                SELECT L.loan_id, L.logged_at, L.isbn, B.title AS book_title, U.name AS user_name, A.action_name
                FROM LOAN_LOGS L
                JOIN (SELECT isbn, MAX(logged_at) AS m FROM LOAN_LOGS GROUP BY isbn) M
                    ON L.isbn = M.isbn AND L.logged_at = M.m
                LEFT JOIN ACTIONS A ON L.action_id = A.action_id
                LEFT JOIN BOOKS B ON L.isbn = B.isbn
                LEFT JOIN USERS U ON L.user_id = U.user_id
                WHERE A.action_name = '貸し出し'
                ORDER BY L.logged_at DESC
                '''
        ).fetchall()
        conn.close()
        return render_template('current_loans.html', rows=rows)


@app.route('/submit', methods=['POST'])
def submit():
    user_id = request.form.get('user_id')
    isbn = request.form.get('isbn')
    action_id = request.form.get('action_id')
    logged_at = request.form.get('logged_at')

    if logged_at:
        logged_at = logged_at.replace('T', ' ')
    else:
        import datetime
        logged_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    try:
        u = conn.execute('SELECT 1 FROM USERS WHERE user_id = ?', (user_id,)).fetchone()
        b = conn.execute('SELECT 1 FROM BOOKS WHERE isbn = ?', (isbn,)).fetchone()
        a = conn.execute('SELECT 1 FROM ACTIONS WHERE action_id = ?', (action_id,)).fetchone()
        if not u or not b or not a:
            flash('選択されたユーザー/書籍/アクションがデータベースに存在しません。', 'error')
            return redirect(url_for('index'))

        conn.execute(
            'INSERT INTO LOAN_LOGS (logged_at, user_id, isbn, action_id) VALUES (?, ?, ?, ?)',
            (logged_at, user_id, isbn, action_id)
        )
        conn.commit()
        flash('記録を追加しました。', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'エラーが発生しました: {e}', 'error')
    finally:
        conn.close()

    return redirect(url_for('index'))


def _find_action_id_by_name(conn, name: str, fallback: int = None):
    try:
        row = conn.execute('SELECT action_id FROM ACTIONS WHERE action_name = ?', (name,)).fetchone()
        if row:
            return row['action_id']
    except Exception:
        pass
    return fallback


def _do_action_internal(user_id: str, isbn: str, action_id: int, logged_at: str = None):
    if logged_at:
        logged_at = logged_at.replace('T', ' ')
    else:
        import datetime
        logged_at = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    try:
        u = conn.execute('SELECT 1 FROM USERS WHERE user_id = ?', (user_id,)).fetchone()
        b = conn.execute('SELECT 1 FROM BOOKS WHERE isbn = ?', (isbn,)).fetchone()
        a = conn.execute('SELECT 1 FROM ACTIONS WHERE action_id = ?', (action_id,)).fetchone()
        if not u or not b or not a:
            return False, '選択されたユーザー/書籍/アクションがデータベースに存在しません。'

        conn.execute(
            'INSERT INTO LOAN_LOGS (logged_at, user_id, isbn, action_id) VALUES (?, ?, ?, ?)',
            (logged_at, user_id, isbn, action_id)
        )
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        app.logger.exception('DB error while performing action')
        return False, str(e)
    finally:
        conn.close()


@app.route('/do/<what>', methods=['GET', 'POST'])
def do_action(what):
    """Perform an action by URL.
    Example: /do/loan?user_id=1&isbn=9784094078263
    Supported `what`: loan, return
    Optional: logged_at (ISO local or 'YYYY-MM-DD HH:MM:SS'), redirect=0 to get JSON response
    """
    allowed = {'loan': '貸し出し', 'return': '返却'}
    if what not in allowed:
        return ('不正なアクションです。', 404)

    user_id = request.values.get('user_id')
    isbn = request.values.get('isbn')
    logged_at = request.values.get('logged_at')
    redirect_flag = request.values.get('redirect', '1')

    if not user_id or not isbn:
        if redirect_flag == '0' or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in (request.headers.get('Accept') or ''):
            return jsonify({'ok': False, 'error': 'missing_parameters', 'message': 'user_id と isbn が必要です'}), 400
        flash('user_id と isbn を指定してください。', 'error')
        return redirect(url_for('index'))

    # Determine action_id by action name if possible; fall back to common IDs
    conn = get_db_connection()
    try:
        action_name_ja = allowed[what]
        action_id = _find_action_id_by_name(conn, action_name_ja, fallback=(1 if what == 'loan' else 2))
    finally:
        conn.close()

    ok, err = _do_action_internal(user_id, isbn, action_id, logged_at)
    if not ok:
        if redirect_flag == '0' or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in (request.headers.get('Accept') or ''):
            return jsonify({'ok': False, 'error': 'db_error', 'message': err}), 500
        flash(f'アクション登録中にエラーが発生しました: {err}', 'error')
        return redirect(url_for('index'))

    # success
    if redirect_flag == '0' or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in (request.headers.get('Accept') or ''):
        return jsonify({'ok': True, 'action': what, 'user_id': user_id, 'isbn': isbn})

    flash(f'アクションを登録しました: {what} (ISBN: {isbn})', 'success')
    return redirect(url_for('index'))


@app.route('/add_book', methods=['POST'])
def add_book():
    isbn = request.form.get('isbn_new', '').strip()
    if not isbn:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'error': 'missing_isbn'}), 400
        flash('ISBNを入力してください。', 'error')
        return redirect(url_for('index'))

    # Fetch metadata from OpenBD
    meta = fetch_openbd(isbn)
    if not meta:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'error': 'openbd_not_found'}), 404
        flash('OpenBDで該当データが見つかりませんでした。手動でタイトルを入力してください。', 'error')
        return redirect(url_for('index'))

    title = meta.get('title') or isbn
    text = meta.get('text')

    conn = get_db_connection()
    try:
        # Determine category from subjects (prefer first subject).
        # If no subject is found, create/use a default category '未分類' to satisfy NOT NULL constraints.
        subjects = meta.get('subjects') or []
        # ensure CATEGORIES table exists (if DB initially had it, this is a no-op)
        conn.execute('CREATE TABLE IF NOT EXISTS CATEGORIES (category_id INTEGER PRIMARY KEY, category_name TEXT UNIQUE)')
        if subjects:
            category_name = subjects[0]
        else:
            category_name = '未分類'

        row = conn.execute('SELECT category_id FROM CATEGORIES WHERE category_name = ?', (category_name,)).fetchone()
        if row:
            category_id = row['category_id']
        else:
            cur = conn.execute('INSERT INTO CATEGORIES (category_name) VALUES (?)', (category_name,))
            category_id = cur.lastrowid

        # Ensure BOOKS table gets the ISBN and title.
        # Some DBs may not have the category_id column; detect columns first.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(BOOKS)").fetchall()]
        if 'category_id' in cols:
            if category_id is not None:
                conn.execute('INSERT OR REPLACE INTO BOOKS (isbn, title, category_id) VALUES (?, ?, ?)', (isbn, title, category_id))
            else:
                conn.execute('INSERT OR REPLACE INTO BOOKS (isbn, title, category_id) VALUES (?, ?, NULL)', (isbn, title))
        else:
            # fallback: insert without category_id
            conn.execute('INSERT OR REPLACE INTO BOOKS (isbn, title) VALUES (?, ?)', (isbn, title))

        # Create details table if not exists to store text content
        conn.execute('''CREATE TABLE IF NOT EXISTS BOOK_DETAILS (
            isbn TEXT PRIMARY KEY,
            text_content TEXT,
            FOREIGN KEY(isbn) REFERENCES BOOKS(isbn)
        )''')
        if text:
            conn.execute('INSERT OR REPLACE INTO BOOK_DETAILS (isbn, text_content) VALUES (?, ?)', (isbn, text))
        conn.commit()
        # If AJAX request, return JSON so frontend can update without reload
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': True, 'isbn': isbn, 'title': title, 'text': text, 'category_id': category_id, 'category_name': category_name})
        flash('書籍を登録しました: {}'.format(title), 'success')
    except Exception as e:
        conn.rollback()
        # log full traceback for server-side debugging
        app.logger.exception('DB error while adding book')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'error': 'db_error', 'message': str(e)}), 500
        flash(f'書籍登録中にエラーが発生しました: {e}', 'error')
    finally:
        conn.close()

    return redirect(url_for('index'))


@app.route('/add_user', methods=['POST'])
def add_user():
    name = request.form.get('user_name_new', '').strip()
    if not name:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'error': 'missing_name'}), 400
        flash('ユーザー名を入力してください。', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    try:
        # Ensure USERS table exists (safe-guard)
        conn.execute('CREATE TABLE IF NOT EXISTS USERS (user_id INTEGER PRIMARY KEY, name TEXT)')
        cur = conn.execute('INSERT INTO USERS (name) VALUES (?)', (name,))
        conn.commit()
        user_id = cur.lastrowid
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': True, 'user_id': user_id, 'name': name})
        flash('ユーザーを追加しました。', 'success')
    except Exception as e:
        conn.rollback()
        app.logger.exception('DB error while adding user')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'error': 'db_error', 'message': str(e)}), 500
        flash(f'ユーザー登録中にエラーが発生しました: {e}', 'error')
    finally:
        conn.close()

    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
