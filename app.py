
import os
import time
import pymysql
from flask import Flask, render_template, request, redirect, abort, url_for

app = Flask(__name__)


def get_db():
    """기존 .env 파일의 설정으로 MySQL에 연결한다."""
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "db"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def init_db():
    """필요한 테이블을 만들고 기존 게시글을 기본 게시판에 연결한다."""
    conn = None

    for _ in range(30):
        try:
            conn = get_db()
            break
        except pymysql.err.OperationalError as e:
            print("DB 준비 중... 2초 후 다시 시도:", e)
            time.sleep(2)

    if conn is None:
        raise RuntimeError("DB에 연결하지 못했습니다.")

    try:
        with conn.cursor() as cur:
            # 게시판 테이블
            cur.execute("""
                CREATE TABLE IF NOT EXISTS boards (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    description VARCHAR(255) NOT NULL DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # 기존 게시글 테이블이 없을 때 생성한다.
            # 기존 테이블이 있다면 기존 게시글은 유지된다.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    title VARCHAR(200) NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # 기존 posts 테이블에 board_id가 없다면 추가한다.
            cur.execute("SHOW COLUMNS FROM posts LIKE 'board_id'")
            if cur.fetchone() is None:
                cur.execute(
                    "ALTER TABLE posts ADD COLUMN board_id INT NULL"
                )

            # 게시판별 글 조회를 위한 인덱스
            cur.execute(
                "SHOW INDEX FROM posts WHERE Key_name = 'idx_posts_board_id'"
            )
            if cur.fetchone() is None:
                cur.execute(
                    "CREATE INDEX idx_posts_board_id ON posts (board_id)"
                )

            # 기본 게시판이 없으면 생성한다.
            cur.execute(
                "SELECT id FROM boards WHERE name = %s",
                ("자유게시판",),
            )
            default_board = cur.fetchone()

            if default_board is None:
                cur.execute(
                    "INSERT INTO boards (name, description) VALUES (%s, %s)",
                    ("자유게시판", "자유롭게 이야기를 나누는 게시판입니다."),
                )
                default_board_id = cur.lastrowid
            else:
                default_board_id = default_board["id"]

            # 기존 게시글 중 게시판이 지정되지 않은 글만 연결한다.
            cur.execute(
                "UPDATE posts SET board_id = %s WHERE board_id IS NULL",
                (default_board_id,),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


@app.route("/")
def index():
    """전체 게시판 목록"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    b.id, b.name, b.description, b.created_at,
                    COUNT(p.id) AS post_count
                FROM boards AS b
                LEFT JOIN posts AS p ON p.board_id = b.id
                GROUP BY
                    b.id, b.name, b.description, b.created_at
                ORDER BY b.id DESC
            """)
            boards = cur.fetchall()
    finally:
        conn.close()

    return render_template("index.html", boards=boards)


@app.route("/boards/create", methods=["POST"])
def create_board():
    """새 게시판 생성"""
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()

    if not name or len(name) > 100 or len(description) > 255:
        abort(400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO boards (name, description) VALUES (%s, %s)",
                (name, description),
            )
        conn.commit()

    except pymysql.err.IntegrityError:
        conn.rollback()
        abort(409, description="같은 이름의 게시판이 이미 존재합니다.")

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect(url_for("index"))


@app.route("/board/<int:board_id>")
def board_view(board_id):
    """선택한 게시판의 게시글 목록과 검색 결과"""
    search = request.args.get("search", "").strip()
    search_type = request.args.get("search_type", "all")

    if search_type not in ("title", "content", "all"):
        search_type = "all"

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM boards WHERE id = %s",
                (board_id,),
            )
            board = cur.fetchone()

            if board is None:
                abort(404)

            sql = """
                SELECT id, title, created_at
                FROM posts
                WHERE board_id = %s
            """
            params = [board_id]

            if search:
                keyword = f"%{search}%"

                if search_type == "title":
                    sql += " AND title LIKE %s"
                    params.append(keyword)

                elif search_type == "content":
                    sql += " AND content LIKE %s"
                    params.append(keyword)

                else:
                    sql += " AND (title LIKE %s OR content LIKE %s)"
                    params.extend([keyword, keyword])

            sql += " ORDER BY id DESC"

            cur.execute(sql, params)
            posts = cur.fetchall()

    finally:
        conn.close()

    return render_template(
        "board.html",
        board=board,
        posts=posts,
        search=search,
        search_type=search_type,
    )


@app.route("/board/<int:board_id>/write", methods=["GET", "POST"])
def write(board_id):
    """선택한 게시판에 게시글 작성"""
    conn = get_db()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name FROM boards WHERE id = %s",
                (board_id,),
            )
            board = cur.fetchone()

            if board is None:
                abort(404)

            if request.method == "POST":
                title = request.form.get("title", "").strip()
                content = request.form.get("content", "").strip()

                if not title or not content or len(title) > 200:
                    abort(400)

                cur.execute(
                    """
                    INSERT INTO posts (board_id, title, content)
                    VALUES (%s, %s, %s)
                    """,
                    (board_id, title, content),
                )
                post_id = cur.lastrowid

                conn.commit()
                return redirect(url_for("view", post_id=post_id))

    finally:
        conn.close()

    return render_template("write.html", board=board)


@app.route("/post/<int:post_id>")
def view(post_id):
    """게시글 상세 조회"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.*, b.name AS board_name
                FROM posts AS p
                JOIN boards AS b ON b.id = p.board_id
                WHERE p.id = %s
                """,
                (post_id,),
            )
            post = cur.fetchone()

            if post is None:
                abort(404)
    finally:
        conn.close()

    return render_template("view.html", post=post)


@app.route("/post/<int:post_id>/edit", methods=["GET", "POST"])
def edit(post_id):
    """게시글 수정"""
    conn = get_db()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM posts WHERE id = %s",
                (post_id,),
            )
            post = cur.fetchone()

            if post is None:
                abort(404)

            if request.method == "POST":
                title = request.form.get("title", "").strip()
                content = request.form.get("content", "").strip()

                if not title or not content or len(title) > 200:
                    abort(400)

                cur.execute(
                    """
                    UPDATE posts
                    SET title = %s, content = %s
                    WHERE id = %s
                    """,
                    (title, content, post_id),
                )
                conn.commit()

                return redirect(url_for("view", post_id=post_id))

    finally:
        conn.close()

    return render_template("edit.html", post=post)


@app.route("/post/<int:post_id>/delete", methods=["POST"])
def delete(post_id):
    """게시글 삭제"""
    conn = get_db()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT board_id FROM posts WHERE id = %s",
                (post_id,),
            )
            post = cur.fetchone()

            if post is None:
                abort(404)

            board_id = post["board_id"]

            cur.execute(
                "DELETE FROM posts WHERE id = %s",
                (post_id,),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect(url_for("board_view", board_id=board_id))


@app.route("/write")
def old_write_url():
    """기존 /write 주소를 기본 게시판 글쓰기 화면으로 연결한다."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM boards ORDER BY id LIMIT 1")
            board = cur.fetchone()
    finally:
        conn.close()

    if board is None:
        abort(404)

    return redirect(url_for("write", board_id=board["id"]))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
