import os
import time
import pymysql
from flask import Flask, render_template, request, redirect, abort

app = Flask(__name__)


def get_db():
    """MySQL에 연결하는 함수. 비밀번호는 .env에서 읽어와요."""
    return pymysql.connect(
        host="db",
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        cursorclass=pymysql.cursors.DictCursor,
    )


def init_db():
    """서버가 켜질 때 DB가 준비될 때까지 기다렸다가 테이블을 만들어요."""
    for _ in range(30):
        try:
            conn = get_db()
            break
        except pymysql.err.OperationalError:
            print("DB 준비 중... 2초 후 다시 시도")
            time.sleep(2)
    else:
        raise RuntimeError("DB에 연결하지 못했어요")

    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.commit()
    conn.close()


@app.route("/")
def index():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT id, title, created_at FROM posts ORDER BY id DESC")
        posts = cur.fetchall()
    conn.close()
    return render_template("index.html", posts=posts)


@app.route("/write", methods=["GET", "POST"])
def write():
    if request.method == "POST":
        title = request.form["title"]
        content = request.form["content"]
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO posts (title, content) VALUES (%s, %s)",
                (title, content),
            )
        conn.commit()
        conn.close()
        return redirect("/")
    return render_template("write.html")


@app.route("/post/<int:post_id>")
def view(post_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
        post = cur.fetchone()
    conn.close()
    if post is None:
        abort(404)
    return render_template("view.html", post=post)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)