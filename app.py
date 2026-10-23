import os
import time
import uuid
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, abort, url_for, session, send_from_directory

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]  # .env 파일에 SECRET_KEY=랜덤문자열 을 넣어야 한다
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 업로드 최대 5MB

UPLOAD_DIR = os.path.join(app.root_path, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "pdf", "txt", "zip", "hwp", "docx", "pptx", "xlsx"}

def get_db():
    """기존 .env 파일의 설정으로 MySQL에 연결한다."""
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "db"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),        
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    

def db_select(sql, params=()):
    # SELECT 전용: 결과 행 목록을 돌려준다
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def db_execute(sql, params=()):
    # INSERT / UPDATE / DELETE 전용: 저장(commit)하고 새로 생긴 번호를 돌려준다
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            new_id = cur.lastrowid
        conn.commit()
        return new_id
    
    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def find_one(sql, params=()):
    # 한 줄만 찾는다. 없으면 404 페이지
    rows = db_select(sql, params)
    if not rows:
        abort(404)
    return rows[0]


def check_owner(post):
    # 내 글이 아니면 403 (로그인 안 했으면 session.get 이 None이라 역시 403)
    if post["user_id"] != session.get("user_id"):
        abort(403)


def can_read(post):
    # 일반 글, 내 글, 비밀번호를 맞힌 비밀글이면 읽을 수 있다
    return (not post["secret_pw_hash"]
            or post["user_id"] == session.get("user_id")
            or session.get(f"unlock_{post['id']}"))


def save_upload(file, allowed=ALLOWED_EXT):
    # 파일을 uploads 폴더에 저장하고 (원래 이름, 저장한 이름) 을 돌려준다
    if not file or not file.filename:
        return None, None   # 파일을 안 올렸으면

    ext = file.filename.rsplit(".",1)[-1].lower()
    if "." not in file.filename or ext not in allowed:
        abort(400, description="허용되지 않은 파일 형식입니다.")


    save_name = f"{uuid.uuid4().hex}.{ext}"  # 겹치치 않는 랜덤 이름
    file.save(os.path.join(UPLOAD_DIR, save_name))
    return file.filename, save_name


def init_db():
    # MySQL 컨테이너가 켜질 때 까지 2초 간격으로 최대 30번 기다린다
    for _ in range(30):
        try:
            get_db().close()
            break
        except pymysql.err.OperationalError:
            print("DB 준비 중... 2초 후 다시 시도")
            time.sleep(2)


    db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            name VARCHAR(50) NOT NULL,
            email VARCHAR(100) NOT NULL UNIQUE,
            school VARCHAR(100) NOT NULL DEFAULT '',
            profile_image VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db_execute("""
        CREATE TABLE IF NOT EXISTS boards (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            description VARCHAR(255) NOT NULL DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db_execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            board_id INT NOT NULL,
            user_id INT NOT NULL,
            title VARCHAR(200) NOT NULL,
            content TEXT NOT NULL,
            secret_pw_hash VARCHAR(255),
            file_name VARCHAR(255),
            file_path VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX (board_id)
        )
    """)
   # 기본 게시판 만들기 (이미 있으면 IGNORE 가 조용히 넘어간다)
    db_execute("""
        INSERT IGNORE INTO boards (name, description) VALUES
            ('자유게시판', '자유롭게 글을 쓸 수 있는 게시판입니다.'),
            ('공지사항', '중요한 공지사항을 확인할 수 있는 게시판입니다.'),
            ('질문과 답변', '질문과 답변을 주고받는 게시판입니다.')
    """)         


@app.route("/")
def index():
    # 게시판 목록 + 게시판마다 글이 몇 개인지
    boards = db_select("""
        SELECT b.id, b.name, b.description, COUNT(p.id) AS post_count
        FROM boards b
        LEFT JOIN posts p ON p.board_id = b.id
        GROUP BY b.id
        ORDER BY b.id DESC
        """)
    return render_template("index.html", boards=boards)


@app.route("/boards/create", methods=["POST"])
def create_board():
    name = request.form["name"].strip()
    description = request.form["description"].strip()

    # 브라우저의 maxlength 는 우회할 수 있으니 서버에서도 검사
    if not name or len(name) > 100 or len(description) > 255:
        abort(400)


    try:
        db_execute(
                "INSERT INTO boards (name, description) VALUES (%s, %s)",
                (name, description),
            )
    except pymysql.err.IntegrityError:  # name 이 UNIQUE 라서 같은 이름이면 에러
        abort(409, description="같은 이름의 게시판이 이미 존재합니다.")


    return redirect(url_for("index"))


@app.route("/board/<int:board_id>")
def board_view(board_id):
    # 게시글 목록 + 검색 (제목 / 내용 / 전체)
    board = find_one("SELECT * FROM boards WHERE id = %s", (board_id,))
    search = request.args.get("search", "").strip()
    search_type = request.args.get("search_type", "all")

    sql = "SELECT id, title, created_at, secret_pw_hash FROM posts WHERE board_id = %s"
    params = [board_id]

    if search:
        keyword = f"%{search}%"  # LIKE '%검색어%' = 검색어가 들어간 글
        if search_type == "title":
            sql += " AND title LIKE %s"
            params.append(keyword)
        elif search_type == "content":
            sql += " AND content LIKE %s AND secret_pw_hash IS NULL"
            params.append(keyword)
        else:
            search_type = "all"
            sql += " AND (title LIKE %s OR (content LIKE %s AND secret_pw_hash IS NULL))"
            params += [keyword, keyword]

    posts = db_select(sql + " ORDER BY id DESC", params)
    return render_template("board.html", board=board, posts=posts, search=search, search_type=search_type)


@app.route("/board/<int:board_id>/write", methods=["GET", "POST"])
def write(board_id):
    # Create
    if "user_id" not in session:
        return redirect(url_for("login"))
    board = find_one("SELECT * FROM boards WHERE id = %s",(board_id,))
    
    if request.method == "POST":
        title = request.form["title"].strip()
        content = request.form["content"].strip()
        secret_pw = request.form.get("secret_pw", "")
        if not title or not content or len(title) > 200:
            abort(400)

        # 비밀번호를 입력했으면 비밀글 (해시로 저장), 비워두면 일반 글 (NULL)
        secret_pw_hash = generate_password_hash(secret_pw) if secret_pw else None
        file_name, file_path = save_upload(request.files.get("file"))

        post_id = db_execute(
            "INSERT INTO posts (board_id, user_id, title, content, secret_pw_hash, file_name, file_path) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (board_id, session["user_id"], title, content, secret_pw_hash, file_name, file_path)
        )
        return redirect(url_for("view", post_id=post_id))


    return render_template("write.html", board=board)


@app.route("/post/<int:post_id>", methods=["GET", "POST"])
def view(post_id):
    # Read
    post = find_one("""
        SELECT p.*, b.name AS board_name, u.username
        FROM posts p
        JOIN boards b ON p.board_id = b.id
        JOIN users u ON p.user_id = u.id
        WHERE p.id = %s
    """, (post_id,))

    # 비밀글이고 내 글이 아니면 비밀번호를 확인한다
    if not can_read(post):
        secret_pw = request.form.get("secret_pw", "")
        if not check_password_hash(post["secret_pw_hash"], secret_pw):
            error = "비밀번호가 올바르지 않습니다." if secret_pw else None
            return render_template("secret.html", post=post, error=error)
        session[f"unlock_{post_id}"] = True  # 맞혔으면 기억 (첨부파일 다운로드용)

    return render_template("view.html", post=post)


@app.route("/post/<int:post_id>/download")
def download(post_id):
    post = find_one("SELECT * FROM posts WHERE id = %s", (post_id,))
    if not post["file_path"]:
        abort(404)
    if not can_read(post):  # 비밀글 첨부파일도 비밀번호를 맞혀야 받을 수 있다
        abort(403)
    return send_from_directory(UPLOAD_DIR, post["file_path"],
                               as_attachment=True, download_name=post["file_name"])
    

@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
def edit(post_id):
    # Update
    post = find_one("SELECT * FROM posts WHERE id = %s", (post_id,))
    check_owner(post)

    if request.method == "POST":
        title = request.form["title"].strip()
        content = request.form["content"].strip()
        if not title or not content or len(title) > 200:
            abort(400)

        db_execute(
            "UPDATE posts SET title = %s, content = %s WHERE id = %s",
            (title, content, post_id),
        )
        return redirect(url_for("view", post_id=post_id))


    return render_template("edit.html", post=post)


@app.route("/post/<int:post_id>/delete", methods=["POST"])
def delete(post_id):
    # Delete
    post = find_one("SELECT board_id, user_id FROM posts WHERE id = %s", (post_id,))
    check_owner(post)
    db_execute("DELETE FROM posts WHERE id = %s", (post_id,))
    return redirect(url_for("board_view", board_id=post["board_id"]))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        name = request.form["name"].strip()
        email = request.form["email"].strip()
        school = request.form["school"].strip()

        if not username or not name or not email or len(password) < 8:
            return render_template("signup.html", error="필수 항목을 입력하고, 비밀번호는 8자 이상이어야 합니다.")

        try:
            db_execute(
                "INSERT INTO users (username, password_hash, name, email, school) VALUES (%s, %s, %s, %s, %s)",
                (username, generate_password_hash(password), name, email, school)
            )
        except pymysql.err.IntegrityError:  # username 또는 email이 UNIQUE 제약 조건에 위배될 때 발생
            return render_template("signup.html", error="이미 존재하는 사용자 아이디 또는 이메일입니다.")

        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        user = db_select("SELECT * FROM users WHERE username = %s", (username,))
        if not user or not check_password_hash(user[0]["password_hash"], password):
            return render_template("login.html", error="아이디 또는 비밀번호가 잘못되었습니다.")

        session.clear()
        session["user_id"] = user[0]["id"]
        session["username"] = user[0]["username"]
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)