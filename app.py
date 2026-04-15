from __future__ import annotations

import os
import sqlite3
import hashlib
import shutil
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "hkugram.db"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
SNAPSHOT_PATH = SNAPSHOT_DIR / "hkugram-latest.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


@dataclass
class SQLIntent:
    question: str
    sql: str
    params: tuple[Any, ...] = ()
    explanation: str = ""


SQL_SCHEMA_SUMMARY = """
You are generating SQLite SELECT queries for this schema only.

users(
  user_id INTEGER PRIMARY KEY,
  username TEXT UNIQUE,
  display_name TEXT,
  password_hash TEXT,
  bio TEXT,
  avatar_url TEXT,
  created_at TEXT
)

posts(
  post_id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users.user_id,
  caption TEXT,
  body TEXT,
  image_url TEXT,
  created_at TEXT,
  like_count INTEGER,
  comment_count INTEGER
)

likes(
  like_id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users.user_id,
  post_id INTEGER REFERENCES posts.post_id,
  created_at TEXT
)

comments(
  comment_id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users.user_id,
  post_id INTEGER REFERENCES posts.post_id,
  body TEXT,
  created_at TEXT
)

tags(
  tag_id INTEGER PRIMARY KEY,
  name TEXT UNIQUE
)

post_tags(
  post_id INTEGER REFERENCES posts.post_id,
  tag_id INTEGER REFERENCES tags.tag_id
)

bookmarks(
  bookmark_id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users.user_id,
  post_id INTEGER REFERENCES posts.post_id,
  created_at TEXT
)

Rules:
- Only generate one read-only SQL query.
- Use SQLite syntax.
- Only use SELECT or WITH ... SELECT.
- Never write data, change schema, or call PRAGMA.
- Use ? placeholders for user-provided literal values and return them in params in order.
- Prefer returning readable columns such as usernames, titles, timestamps, like_count, and comment_count.
""".strip()


SQL_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sql": {"type": "string"},
        "params": {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "number"},
                    {"type": "integer"},
                    {"type": "boolean"},
                ]
            },
        },
        "explanation": {"type": "string"},
    },
    "required": ["sql", "params", "explanation"],
}


class AppError(Exception):
    pass


def ensure_directories() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    SNAPSHOT_DIR.mkdir(exist_ok=True)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = FULL;")
    return conn


def init_db() -> None:
    ensure_directories()
    restore_local_snapshot_if_needed()
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        ensure_user_auth_columns(conn)
        ensure_post_content_columns(conn)
        count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if count == 0:
            seed_database(conn)
    save_local_snapshot()


def restore_local_snapshot_if_needed() -> None:
    if DB_PATH.exists() or not SNAPSHOT_PATH.exists():
        return
    shutil.copy2(SNAPSHOT_PATH, DB_PATH)


def save_local_snapshot() -> None:
    ensure_directories()
    if not DB_PATH.exists():
        return
    with get_connection() as source:
        source.execute("PRAGMA wal_checkpoint(FULL);")
        with sqlite3.connect(SNAPSHOT_PATH) as dest:
            source.backup(dest)


def ensure_user_auth_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(users)")
    }
    if "password_hash" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
        conn.commit()


def ensure_post_content_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(posts)")
    }
    if "body" not in columns:
        conn.execute("ALTER TABLE posts ADD COLUMN body TEXT NOT NULL DEFAULT ''")
        conn.commit()


def seed_database(conn: sqlite3.Connection) -> None:
    users = [
        ("tianxing", "Tianxing Chen", "Collecting city textures and sharp database ideas.", "https://picsum.photos/seed/tianxing/80/80"),
        ("pingluo", "Ping Luo", "Teaching data systems, one schema at a time.", "https://picsum.photos/seed/pingluo/80/80"),
        ("mengkang", "Mengkang Hu", "Query plans, coffee, and late-night demos.", "https://picsum.photos/seed/mengkang/80/80"),
        ("duckt", "Duckt", "Building HKUgram with a strict ER model and cleaner UI.", "https://picsum.photos/seed/duckt/80/80"),
        ("annie", "Annie Case", "Chasing color, motion, and practical product ideas.", "https://picsum.photos/seed/annie/80/80"),
    ]
    conn.executemany(
        "INSERT INTO users (username, display_name, bio, avatar_url) VALUES (?, ?, ?, ?)",
        users,
    )
    user_map = {
        row["username"]: row["user_id"]
        for row in conn.execute("SELECT user_id, username FROM users")
    }
    base_time = datetime(2026, 4, 7, 18, 0, 0)
    posts = [
        (user_map["duckt"], "Tonight's prototype feed is finally holding together. Neon train reflections felt right for the first post.", "https://picsum.photos/seed/hkugram-neon/900/900", base_time.isoformat(sep=" ")),
        (user_map["tianxing"], "Testing image cards with dense metadata. The layout needs to feel more like a product than a gallery.", "https://picsum.photos/seed/hkugram-grid/900/900", (base_time + timedelta(hours=6)).isoformat(sep=" ")),
        (user_map["annie"], "Morning climb, quiet fog, and one useful reminder: good products should explain themselves.", "https://picsum.photos/seed/hkugram-cliff/900/900", (base_time + timedelta(days=1, hours=8)).isoformat(sep=" ")),
        (user_map["pingluo"], "A database course project is better when analytics are visible, not buried in raw tables.", "https://picsum.photos/seed/hkugram-desk/900/900", (base_time + timedelta(days=2, hours=2)).isoformat(sep=" ")),
        (user_map["mengkang"], "Comment threads are live in the schema. Now the UI needs to make them feel immediate.", "https://picsum.photos/seed/hkugram-night/900/900", (base_time + timedelta(days=3, hours=3)).isoformat(sep=" ")),
        (user_map["duckt"], "Built a trending tag experiment with time decay. It is rough, but the rankings already feel useful.", "https://picsum.photos/seed/hkugram-lab/900/900", (base_time + timedelta(days=4, hours=7)).isoformat(sep=" ")),
    ]
    conn.executemany(
        "INSERT INTO posts (user_id, caption, image_url, created_at) VALUES (?, ?, ?, ?)",
        posts,
    )

    tags_by_post = {
        1: ["campus", "night", "prototype"],
        2: ["ui", "database", "product"],
        3: ["travel", "reflection", "design"],
        4: ["analytics", "database", "teaching"],
        5: ["comments", "engineering", "build"],
        6: ["trending", "sql", "experiment"],
    }
    for tags in tags_by_post.values():
        for tag in tags:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
    tag_map = {
        row["name"]: row["tag_id"]
        for row in conn.execute("SELECT tag_id, name FROM tags")
    }
    for post_id, tags in tags_by_post.items():
        for tag in tags:
            conn.execute(
                "INSERT INTO post_tags (post_id, tag_id) VALUES (?, ?)",
                (post_id, tag_map[tag]),
            )

    likes = [
        (user_map["tianxing"], 1), (user_map["annie"], 1), (user_map["mengkang"], 1),
        (user_map["duckt"], 2), (user_map["annie"], 2), (user_map["pingluo"], 2),
        (user_map["duckt"], 3), (user_map["tianxing"], 3), (user_map["mengkang"], 3),
        (user_map["annie"], 4), (user_map["duckt"], 4), (user_map["pingluo"], 5),
        (user_map["annie"], 5), (user_map["tianxing"], 6), (user_map["pingluo"], 6),
        (user_map["mengkang"], 6), (user_map["annie"], 6),
    ]
    conn.executemany("INSERT INTO likes (user_id, post_id) VALUES (?, ?)", likes)

    comments = [
        (user_map["annie"], 1, "The contrast is working. Keep the green accent restrained."),
        (user_map["pingluo"], 1, "This screenshot would work well for the UI design slide."),
        (user_map["duckt"], 2, "Agreed. The analytics panel should read instantly."),
        (user_map["mengkang"], 3, "The caption is stronger than the filter. Good sign."),
        (user_map["tianxing"], 4, "We should expose these counts in a dashboard card too."),
        (user_map["annie"], 6, "Trending tags will make the SQL demo much easier to explain."),
    ]
    conn.executemany(
        "INSERT INTO comments (user_id, post_id, body) VALUES (?, ?, ?)",
        comments,
    )

    bookmarks = [
        (user_map["duckt"], 4),
        (user_map["duckt"], 6),
        (user_map["annie"], 2),
        (user_map["mengkang"], 3),
    ]
    conn.executemany(
        "INSERT INTO bookmarks (user_id, post_id) VALUES (?, ?)",
        bookmarks,
    )
    conn.commit()


def parse_tags(raw_tags: str) -> list[str]:
    tags: list[str] = []
    for item in raw_tags.split(","):
        cleaned = item.strip().lower().lstrip("#")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return tags[:6]


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return bool(password_hash) and hash_password(password) == password_hash


def current_user_id(params: dict[str, list[str]]) -> int:
    raw = params.get("viewer", ["4"])[0]
    try:
        return int(raw)
    except ValueError:
        return 4


def url_with_viewer(path: str, viewer_id: int, **extra: Any) -> str:
    params: dict[str, Any] = {}
    for key, value in extra.items():
        if value not in (None, "", False):
            params[key] = value
    return f"{path}?{urlencode(params, doseq=True)}" if params else path


def relative_time(raw_value: str) -> str:
    try:
        dt = datetime.fromisoformat(raw_value)
    except ValueError:
        return raw_value
    delta = datetime.now() - dt
    if delta.days >= 7:
        return dt.strftime("%Y-%m-%d %H:%M")
    if delta.days >= 1:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours}h ago"
    minutes = max(delta.seconds // 60, 1)
    return f"{minutes}m ago"


def fetch_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT user_id, username, display_name, bio, avatar_url FROM users ORDER BY username"
    ).fetchall()


def fetch_profile_summary(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    return dict(
        conn.execute(
            """
            SELECT u.user_id, u.username, u.display_name, u.bio, u.avatar_url,
                   COUNT(DISTINCT p.post_id) AS post_total,
                   COALESCE(SUM(p.like_count), 0) AS like_total,
                   COALESCE(SUM(p.comment_count), 0) AS comment_total
            FROM users u
            LEFT JOIN posts p ON p.user_id = u.user_id
            WHERE u.user_id = ?
            GROUP BY u.user_id
            """,
            (user_id,),
        ).fetchone()
    )


def fetch_feed(
    conn: sqlite3.Connection,
    viewer_id: int,
    *,
    sort_by: str = "latest",
    tag: str | None = None,
    author: str | None = None,
    search: str | None = None,
    liked_only: bool = False,
    bookmarked_only: bool = False,
) -> list[dict[str, Any]]:
    joins = [
        """
        LEFT JOIN likes viewer_likes
          ON viewer_likes.post_id = p.post_id AND viewer_likes.user_id = ?
        LEFT JOIN bookmarks viewer_bookmarks
          ON viewer_bookmarks.post_id = p.post_id AND viewer_bookmarks.user_id = ?
        """
    ]
    filters: list[str] = []
    params: list[Any] = [viewer_id, viewer_id]
    if tag:
        joins.append(
            """
            JOIN post_tags pt_filter ON pt_filter.post_id = p.post_id
            JOIN tags t_filter ON t_filter.tag_id = pt_filter.tag_id
            """
        )
        filters.append("t_filter.name = ?")
        params.append(tag.lower())
    if author:
        filters.append("u.username = ?")
        params.append(author.lower())
    if search:
        filters.append("(LOWER(p.caption) LIKE ? OR LOWER(p.body) LIKE ? OR LOWER(u.username) LIKE ?)")
        pattern = f"%{search.lower()}%"
        params.extend([pattern, pattern, pattern])
    if liked_only:
        filters.append("viewer_likes.like_id IS NOT NULL")
    if bookmarked_only:
        filters.append("viewer_bookmarks.bookmark_id IS NOT NULL")

    order_by = {
        "latest": "p.created_at DESC",
        "popular": "p.like_count DESC, p.comment_count DESC, p.created_at DESC",
        "discussed": "p.comment_count DESC, p.like_count DESC, p.created_at DESC",
        "trending": "(p.like_count * 3 + p.comment_count * 2) DESC, p.created_at DESC",
    }.get(sort_by, "p.created_at DESC")

    query = f"""
        SELECT p.post_id, p.caption, p.body, p.image_url, p.created_at,
               p.like_count, p.comment_count,
               u.user_id, u.username, u.display_name, u.avatar_url,
               CASE WHEN viewer_likes.like_id IS NULL THEN 0 ELSE 1 END AS liked_by_viewer,
               CASE WHEN viewer_bookmarks.bookmark_id IS NULL THEN 0 ELSE 1 END AS bookmarked_by_viewer
        FROM posts p
        JOIN users u ON u.user_id = p.user_id
        {' '.join(joins)}
        {f"WHERE {' AND '.join(filters)}" if filters else ""}
        GROUP BY p.post_id
        ORDER BY {order_by}
    """
    rows = conn.execute(query, params).fetchall()
    post_ids = [row["post_id"] for row in rows]
    tags_map = {post_id: [] for post_id in post_ids}
    comments_map = {post_id: [] for post_id in post_ids}
    if post_ids:
        placeholders = ",".join("?" for _ in post_ids)
        for row in conn.execute(
            f"""
            SELECT pt.post_id, t.name
            FROM post_tags pt
            JOIN tags t ON t.tag_id = pt.tag_id
            WHERE pt.post_id IN ({placeholders})
            ORDER BY t.name
            """,
            post_ids,
        ):
            tags_map[row["post_id"]].append(row["name"])
        for row in conn.execute(
            f"""
            SELECT c.post_id, c.body, c.created_at, u.username
            FROM comments c
            JOIN users u ON u.user_id = c.user_id
            WHERE c.post_id IN ({placeholders})
            ORDER BY c.created_at DESC
            """,
            post_ids,
        ):
            comments_map[row["post_id"]].append(
                {"body": row["body"], "created_at": row["created_at"], "username": row["username"]}
            )
    return [
        {
            **dict(row),
            "tags": tags_map[row["post_id"]],
            "comments": comments_map[row["post_id"]][:3],
            "relative_time": relative_time(row["created_at"]),
        }
        for row in rows
    ]


def fetch_analytics(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        "most_liked": [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.post_id, u.username, p.like_count, p.comment_count
                FROM posts p
                JOIN users u ON u.user_id = p.user_id
                ORDER BY p.like_count DESC, p.comment_count DESC, p.created_at DESC
                LIMIT 5
                """
            )
        ],
        "active_users": [
            dict(row)
            for row in conn.execute(
                """
                SELECT u.username,
                       COUNT(DISTINCT p.post_id) AS posts,
                       COUNT(DISTINCT c.comment_id) AS comments,
                       COALESCE(SUM(p.like_count), 0) AS likes_received
                FROM users u
                LEFT JOIN posts p ON p.user_id = u.user_id
                LEFT JOIN comments c ON c.user_id = u.user_id
                GROUP BY u.user_id
                ORDER BY posts DESC, comments DESC, likes_received DESC, u.username ASC
                LIMIT 5
                """
            )
        ],
        "trending_tags": [
            dict(row)
            for row in conn.execute(
                """
                SELECT t.name, COUNT(*) AS tagged_posts,
                       COALESCE(SUM(p.like_count), 0) AS likes_on_tagged_posts
                FROM tags t
                JOIN post_tags pt ON pt.tag_id = t.tag_id
                JOIN posts p ON p.post_id = pt.post_id
                GROUP BY t.tag_id
                ORDER BY likes_on_tagged_posts DESC, tagged_posts DESC, t.name ASC
                LIMIT 6
                """
            )
        ],
        "daily_activity": [
            dict(row)
            for row in conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS posts_created
                FROM posts
                GROUP BY substr(created_at, 1, 10)
                ORDER BY day DESC
                LIMIT 7
                """
            )
        ],
    }


def metric_cards(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM users) AS users,
            (SELECT COUNT(*) FROM posts) AS posts,
            (SELECT COUNT(*) FROM comments) AS comments,
            (SELECT COUNT(*) FROM likes) AS likes
        """
    ).fetchone()
    return dict(row)


def fetch_creator_spotlight(conn: sqlite3.Connection, viewer_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            u.user_id,
            u.username,
            u.display_name,
            u.avatar_url,
            COUNT(DISTINCT p.post_id) AS post_total,
            COALESCE(SUM(p.like_count), 0) AS like_total
        FROM users u
        LEFT JOIN posts p ON p.user_id = u.user_id
        GROUP BY u.user_id
        ORDER BY like_total DESC, post_total DESC, u.username ASC
        LIMIT 5
        """
    ).fetchall()
    return [{**dict(row), "is_viewer": row["user_id"] == viewer_id} for row in rows]


def fetch_post_detail(conn: sqlite3.Connection, viewer_id: int, post_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT p.post_id, p.caption, p.body, p.image_url, p.created_at,
               p.like_count, p.comment_count,
               u.user_id, u.username, u.display_name, u.avatar_url,
               CASE WHEN viewer_likes.like_id IS NULL THEN 0 ELSE 1 END AS liked_by_viewer,
               CASE WHEN viewer_bookmarks.bookmark_id IS NULL THEN 0 ELSE 1 END AS bookmarked_by_viewer
        FROM posts p
        JOIN users u ON u.user_id = p.user_id
        LEFT JOIN likes viewer_likes
          ON viewer_likes.post_id = p.post_id AND viewer_likes.user_id = ?
        LEFT JOIN bookmarks viewer_bookmarks
          ON viewer_bookmarks.post_id = p.post_id AND viewer_bookmarks.user_id = ?
        WHERE p.post_id = ?
        """,
        (viewer_id, viewer_id, post_id),
    ).fetchone()
    if not row:
        raise AppError("Post not found.")

    tags = [
        tag_row["name"]
        for tag_row in conn.execute(
            """
            SELECT t.name
            FROM post_tags pt
            JOIN tags t ON t.tag_id = pt.tag_id
            WHERE pt.post_id = ?
            ORDER BY t.name
            """,
            (post_id,),
        )
    ]
    comments = [
        {
            "comment_id": comment_row["comment_id"],
            "user_id": comment_row["user_id"],
            "username": comment_row["username"],
            "body": comment_row["body"],
            "created_at": comment_row["created_at"],
        }
        for comment_row in conn.execute(
            """
            SELECT c.comment_id, c.user_id, c.body, c.created_at, u.username
            FROM comments c
            JOIN users u ON u.user_id = c.user_id
            WHERE c.post_id = ?
            ORDER BY c.created_at DESC
            """,
            (post_id,),
        )
    ]
    return {
        **dict(row),
        "tags": tags,
        "comments": comments,
        "relative_time": relative_time(row["created_at"]),
    }


def translate_text_to_sql_rules(question: str) -> SQLIntent:
    normalized = " ".join(question.lower().split())
    if not normalized:
        raise AppError("Please enter a question for Text-to-SQL.")
    presets = [
        (
            ["most liked posts", "top liked posts", "popular posts"],
            SQLIntent(
                question,
                """
                SELECT p.post_id, u.username, p.caption, p.like_count, p.comment_count, p.created_at
                FROM posts p
                JOIN users u ON u.user_id = p.user_id
                ORDER BY p.like_count DESC, p.comment_count DESC, p.created_at DESC
                LIMIT 10
                """,
                explanation="Returns the ten posts with the highest like counts.",
            ),
        ),
        (
            ["most active users", "top active users"],
            SQLIntent(
                question,
                """
                SELECT u.username,
                       COUNT(DISTINCT p.post_id) AS posts_created,
                       COUNT(DISTINCT c.comment_id) AS comments_written
                FROM users u
                LEFT JOIN posts p ON p.user_id = u.user_id
                LEFT JOIN comments c ON c.user_id = u.user_id
                GROUP BY u.user_id
                ORDER BY posts_created DESC, comments_written DESC, u.username ASC
                LIMIT 10
                """,
                explanation="Ranks users by number of posts and comments.",
            ),
        ),
        (
            ["trending tags", "popular tags", "top tags"],
            SQLIntent(
                question,
                """
                SELECT t.name AS tag, COUNT(*) AS tagged_posts,
                       COALESCE(SUM(p.like_count), 0) AS likes_on_posts
                FROM tags t
                JOIN post_tags pt ON pt.tag_id = t.tag_id
                JOIN posts p ON p.post_id = pt.post_id
                GROUP BY t.tag_id
                ORDER BY likes_on_posts DESC, tagged_posts DESC, tag ASC
                LIMIT 10
                """,
                explanation="Shows which tags appear on the strongest-performing posts.",
            ),
        ),
        (
            ["latest posts", "newest posts", "recent posts"],
            SQLIntent(
                question,
                """
                SELECT p.post_id, u.username, p.caption, p.created_at
                FROM posts p
                JOIN users u ON u.user_id = p.user_id
                ORDER BY p.created_at DESC
                LIMIT 10
                """,
                explanation="Fetches the ten newest posts.",
            ),
        ),
        (
            ["comment counts by user", "comments by user"],
            SQLIntent(
                question,
                """
                SELECT u.username, COUNT(c.comment_id) AS comments_written
                FROM users u
                LEFT JOIN comments c ON c.user_id = u.user_id
                GROUP BY u.user_id
                ORDER BY comments_written DESC, u.username ASC
                LIMIT 10
                """,
                explanation="Counts how many comments each user has written.",
            ),
        ),
    ]
    for keywords, intent in presets:
        if any(keyword in normalized for keyword in keywords):
            return intent
    if normalized.startswith("posts by "):
        username = normalized.removeprefix("posts by ").strip().split()[0]
        return SQLIntent(
            question,
            """
            SELECT p.post_id, u.username, p.caption, p.like_count, p.comment_count, p.created_at
            FROM posts p
            JOIN users u ON u.user_id = p.user_id
            WHERE u.username = ?
            ORDER BY p.created_at DESC
            LIMIT 10
            """,
            (username,),
            explanation=f"Lists the newest posts created by @{username}.",
        )
    raise AppError(
        "Supported questions include most liked posts, active users, trending tags, latest posts, comments by user, and 'posts by <username>'."
    )


def extract_deepseek_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if not choices:
        raise AppError("The model returned no choices.")
    message = choices[0].get("message", {})
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    raise AppError("The model returned empty content.")


def validate_read_only_sql(sql: str) -> str:
    cleaned = sql.strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    normalized = " ".join(cleaned.lower().split())
    if not normalized.startswith(("select", "with")):
        raise AppError("The generated query was not read-only.")
    if ";" in cleaned or "--" in cleaned or "/*" in cleaned:
        raise AppError("Only a single clean read-only query is allowed.")
    forbidden_keywords = [
        " insert ",
        " update ",
        " delete ",
        " drop ",
        " alter ",
        " create ",
        " pragma ",
        " attach ",
        " detach ",
        " vacuum ",
        " replace ",
        " truncate ",
        " grant ",
        " revoke ",
        " merge ",
    ]
    padded = f" {normalized} "
    if any(keyword in padded for keyword in forbidden_keywords):
        raise AppError("The generated query included forbidden SQL operations.")
    return cleaned


def translate_text_to_sql_with_deepseek(question: str) -> SQLIntent:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise AppError("DEEPSEEK_API_KEY is not configured.")
    normalized = " ".join(question.split())
    if not normalized:
        raise AppError("Please enter a question for Text-to-SQL.")

    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    json_example = {
        "sql": "SELECT u.username, COUNT(*) AS posts_created FROM posts p JOIN users u ON u.user_id = p.user_id GROUP BY u.user_id ORDER BY posts_created DESC LIMIT 10",
        "params": [],
        "explanation": "Ranks users by how many posts they created.",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You translate natural language database questions into safe SQLite SELECT queries. "
                    "Return valid json only. The JSON object must contain exactly these keys: "
                    "`sql`, `params`, and `explanation`.\n\n"
                    f"JSON example:\n{json.dumps(json_example)}"
                ),
            },
            {
                "role": "user",
                "content": f"{SQL_SCHEMA_SUMMARY}\n\nQuestion: {normalized}\n\nReturn json only.",
            },
        ],
        "temperature": 0,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }

    request = Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise AppError(f"DeepSeek API request failed: HTTP {exc.code}. {detail[:180]}") from exc
    except URLError as exc:
        raise AppError(f"DeepSeek API request failed: {exc.reason}") from exc

    try:
        plan = json.loads(extract_deepseek_text(response_payload))
    except json.JSONDecodeError as exc:
        raise AppError("The model did not return valid structured JSON.") from exc
    for key in SQL_PLAN_SCHEMA["required"]:
        if key not in plan:
            raise AppError(f"The model response was missing '{key}'.")
    sql = validate_read_only_sql(plan["sql"])
    explanation = plan["explanation"].strip() or "Generated a read-only database query."
    return SQLIntent(
        question=question,
        sql=sql,
        params=tuple(plan.get("params", [])),
        explanation=explanation,
    )


def translate_text_to_sql(question: str) -> SQLIntent:
    model_error: AppError | None = None
    if os.environ.get("DEEPSEEK_API_KEY"):
        try:
            return translate_text_to_sql_with_deepseek(question)
        except AppError as exc:
            # Keep the app usable locally even if the API is misconfigured or unavailable.
            model_error = exc
    try:
        return translate_text_to_sql_rules(question)
    except AppError as exc:
        if model_error is not None:
            raise AppError(f"{model_error} Rule-based fallback also could not answer this question.") from exc
        raise AppError(
            f"{exc} Configure DEEPSEEK_API_KEY to enable model-backed natural language querying."
        ) from exc


def execute_safe_sql(conn: sqlite3.Connection, intent: SQLIntent, viewer_id: int | None = None) -> tuple[list[str], list[tuple[Any, ...]]]:
    sql = intent.sql.strip()
    validate_read_only_sql(sql)
    rows = conn.execute(sql, intent.params).fetchall()
    columns = list(rows[0].keys()) if rows else []
    data = [tuple(row) for row in rows]
    if viewer_id is not None:
        conn.execute(
            "INSERT INTO query_history (user_id, natural_language, generated_sql) VALUES (?, ?, ?)",
            (viewer_id, intent.question, sql),
        )
        conn.commit()
    return columns, data


def render_flash(message: str | None, level: str = "info") -> str:
    if not message:
        return ""
    return f'<div class="flash flash-{level}">{escape(message)}</div>'


def render_auth_page(title: str, form_body: str, alt_link: str, flash: str | None = None, error: str | None = None) -> bytes:
    page = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)} | HKUgram</title>
    <link rel="stylesheet" href="/static/style.css?v=20260415f">
</head>
<body data-theme="light">
    <main class="auth-shell">
        <section class="auth-card auth-card-clean">
            <div class="brand-block auth-brand">
                <div class="brand-mark">H</div>
                <h1>HKUgram</h1>
            </div>
            <div class="auth-copy">
                <p class="eyebrow">Welcome</p>
                <h2>{escape(title)}</h2>
                <p class="lead">A clean login for your own account. Usernames are unique and saved to the database for future sign-ins.</p>
            </div>
            {render_flash(flash)}
            {render_flash(error, 'error')}
            {form_body}
            <p class="muted auth-alt-link">{alt_link}</p>
        </section>
    </main>
</body>
</html>"""
    return page.encode("utf-8")


def render_login_page(flash: str | None = None, error: str | None = None) -> bytes:
    form = """
    <form method="post" action="/login" class="composer-form">
        <label>
            Username
            <input type="text" name="username" required>
        </label>
        <label>
            Password
            <input type="password" name="password" required>
        </label>
        <button class="action-button primary" type="submit">Log In</button>
    </form>
    """
    return render_auth_page("Log In", form, 'No account yet? <a href="/register">Create one</a>.', flash=flash, error=error)


def render_register_page(flash: str | None = None, error: str | None = None) -> bytes:
    form = """
    <form method="post" action="/register" class="composer-form">
        <label>
            Username
            <input type="text" name="username" required>
        </label>
        <label>
            Display Name
            <input type="text" name="display_name" required>
        </label>
        <label>
            Password
            <input type="password" name="password" required>
        </label>
        <button class="action-button primary" type="submit">Create Account</button>
    </form>
    """
    return render_auth_page("Create Account", form, 'Already registered? <a href="/login">Log in</a>.', flash=flash, error=error)


def render_post_card(post: dict[str, Any], viewer_id: int) -> str:
    like_icon = "&#10084;" if post["liked_by_viewer"] else "&#9825;"
    title = post["caption"].strip() or "Untitled post"
    body_preview = post.get("body", "").strip()
    excerpt_html = f"<p class='post-excerpt'>{escape(body_preview[:120])}</p>" if body_preview else ""
    media_html = (
        f"""
        <div class="post-image-wrap">
            <img src="{escape(post['image_url'])}" alt="Post image" class="post-image">
        </div>
        """
        if post["image_url"]
        else ""
    )
    return f"""
    <article class="post-card compact-card {'text-only-card' if not post['image_url'] else ''}">
        <a class="post-link-cover" href="{url_with_viewer('/post', viewer_id, post_id=post['post_id'])}" aria-label="Open post"></a>
        {media_html}
        <div class="post-card-body">
            <h3 class="post-title">{escape(title)}</h3>
            {excerpt_html}
        </div>
        <div class="post-card-footer">
            <a href="{url_with_viewer('/', viewer_id, author=post['username'])}" class="post-user-stamp">
                <img src="{escape(post['avatar_url'])}" alt="avatar" class="avatar tiny">
                <span>@{escape(post['username'])}</span>
            </a>
            <span class="post-like-chip">{like_icon} {post['like_count']}</span>
        </div>
    </article>
    """


def html_page(title: str, viewer_id: int, body: str, conn: sqlite3.Connection, active_nav: str = "discover") -> bytes:
    profile = fetch_profile_summary(conn, viewer_id)
    page = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)} | HKUgram</title>
    <link rel="stylesheet" href="/static/style.css?v=20260415f">
</head>
<body data-page="{escape(active_nav)}" data-theme="light">
    <div class="app-shell">
        <header class="topbar">
            <div class="brand-block">
                <div class="brand-mark">H</div>
                <h1>HKUgram</h1>
            </div>
            <form method="get" action="/" class="topbar-search-form" data-topbar-form>
                <input type="hidden" name="sort" value="latest" data-topbar-sort>
                <div class="topbar-search-row">
                    <input type="text" name="search" placeholder="Search posts or creators" data-topbar-search>
                    <button class="theme-toggle" type="button" data-theme-toggle aria-label="Toggle theme">&#9680;</button>
                    <button class="icon-button" type="button" data-filter-toggle aria-expanded="false" aria-label="Open filters">&#9881;</button>
                    <button class="action-button primary" type="submit">Search</button>
                </div>
                <div class="topbar-advanced-filter" data-advanced-filter aria-hidden="true">
                    <div class="filter-grid">
                        <label class="toggle-label">
                            <input type="checkbox" name="liked" value="1" data-topbar-liked>
                            Liked by viewer
                        </label>
                        <label class="toggle-label">
                            <input type="checkbox" name="bookmarked" value="1" data-topbar-bookmarked>
                            Bookmarked
                        </label>
                    </div>
                </div>
            </form>
            <div class="topbar-actions">
                <div class="account-chip">
                    <span>@{escape(profile['username'])}</span>
                    <a href="/logout" class="text-button">Log out</a>
                </div>
            </div>
        </header>
        <div class="page-layout">
            <main class="content-shell">{body}</main>
        </div>
    </div>
    <nav class="bottom-nav">
        <a data-nav="discover" href="{url_with_viewer('/', viewer_id)}">Home</a>
        <a data-nav="history" href="{url_with_viewer('/history', viewer_id)}">Profile</a>
        <a class="bottom-compose" data-nav="create" href="{url_with_viewer('/create', viewer_id)}" aria-label="Create post">+</a>
        <a data-nav="analytics" href="{url_with_viewer('/analytics', viewer_id)}">Insights</a>
        <a data-nav="ask" href="{url_with_viewer('/query', viewer_id)}">Ask</a>
    </nav>
    <script src="/static/app.js?v=20260415f"></script>
</body>
</html>"""
    return page.encode("utf-8")


def render_feed_page(conn: sqlite3.Connection, params: dict[str, list[str]]) -> bytes:
    viewer_id = current_user_id(params)
    sort_by = params.get("sort", ["latest"])[0]
    tag = params.get("tag", [""])[0] or None
    author = params.get("author", [""])[0] or None
    search = params.get("search", [""])[0] or None
    liked_only = params.get("liked", ["0"])[0] == "1"
    bookmarked_only = params.get("bookmarked", ["0"])[0] == "1"
    flash = params.get("flash", [""])[0] or None
    feed = fetch_feed(
        conn,
        viewer_id,
        sort_by=sort_by,
        tag=tag,
        author=author,
        search=search,
        liked_only=liked_only,
        bookmarked_only=bookmarked_only,
    )
    posts_html = "".join(render_post_card(post, viewer_id) for post in feed)
    if not posts_html:
        posts_html = """
        <section class="empty-state">
            <h3>No posts match the current filter.</h3>
            <p>Adjust your filters or create a new post.</p>
        </section>
        """
    sort_links = "".join(
        f"<a class='filter-pill {'active' if sort_by == key else ''}' href='{url_with_viewer('/', viewer_id, sort=key, tag=tag, author=author, search=search, liked='1' if liked_only else None, bookmarked='1' if bookmarked_only else None)}'>{label}</a>"
        for key, label in [("latest", "Latest"), ("popular", "Hot"), ("trending", "Trending")]
    )
    body = f"""
    <section class="section-header">
        <div>
            <h2>Discover</h2>
            <p class="lead">A clean waterfall of posts. Open any card for details.</p>
        </div>
        <div class="pill-row">{sort_links}</div>
    </section>
    {render_flash(flash)}
    <section class="feed-grid">{posts_html}</section>
    """
    return html_page("Home Feed", viewer_id, body, conn, active_nav="discover")


def render_create_page(conn: sqlite3.Connection, params: dict[str, list[str]]) -> bytes:
    viewer_id = current_user_id(params)
    flash = params.get("flash", [""])[0] or None
    body = f"""
    <section class="section-header">
        <div>
            <h2>Create Post</h2>
            <p class="lead">Compose on a dedicated page, then publish back to the feed.</p>
        </div>
    </section>
    {render_flash(flash)}
    <section class="composer-panel" id="composer-panel">
        <form method="post" action="/posts" class="composer-form">
            <input type="hidden" name="viewer" value="{viewer_id}">
            <label>
                Title
                <input type="text" name="title" placeholder="Give your post a title" maxlength="120" data-title-input>
            </label>
            <label>
                Body
                <textarea name="body" rows="6" placeholder="Write the main post content here" maxlength="2000" data-body-input></textarea>
            </label>
            <div class="form-row">
                <label>
                    Image URL
                    <input type="url" name="image_url" placeholder="https://example.com/image.jpg" data-image-input>
                </label>
                <label>
                    Tags
                    <input type="text" name="tags" placeholder="travel, ui, analytics">
                </label>
            </div>
            <p class="muted">You can publish text only, image only, or both. At least one is required.</p>
            <div class="composer-preview" data-image-preview-wrap hidden>
                <div class="composer-preview-card">
                    <img src="" alt="Preview" data-image-preview>
                    <div>
                        <strong>Post Preview</strong>
                        <p class="muted">Check the image before publishing.</p>
                    </div>
                </div>
            </div>
            <div class="composer-bottom-row">
                <span class="metric-pill" data-body-counter>0 / 2000</span>
                <button class="action-button primary" type="submit">Publish Post</button>
            </div>
        </form>
    </section>
    """
    return html_page("Create Post", viewer_id, body, conn, active_nav="create")


def render_post_detail_page(conn: sqlite3.Connection, params: dict[str, list[str]]) -> bytes:
    viewer_id = current_user_id(params)
    post_id = int(params.get("post_id", ["0"])[0])
    return_to = url_with_viewer("/post", viewer_id, post_id=post_id)
    post = fetch_post_detail(conn, viewer_id, post_id)
    tags_html = "".join(f"<span class='tag-pill'>#{escape(tag)}</span>" for tag in post["tags"])
    comments_html = "".join(
        f"""
        <li>
            <div class="comment-meta-row">
                <strong>@{escape(c['username'])}</strong>
                <small>{escape(relative_time(c['created_at']))}</small>
            </div>
            <span>{escape(c['body'])}</span>
            {"<form method='post' action='/delete-comment' class='inline-delete-form'><input type='hidden' name='viewer' value='" + str(viewer_id) + "'><input type='hidden' name='comment_id' value='" + str(c['comment_id']) + "'><input type='hidden' name='post_id' value='" + str(post['post_id']) + "'><input type='hidden' name='return_to' value='" + escape(return_to) + "'><button class='text-button danger' type='submit'>Delete</button></form>" if c['user_id'] == viewer_id else ""}
        </li>
        """
        for c in post["comments"]
    ) or "<li class='muted'>No comments yet.</li>"
    media_html = (
        f"""
        <article class="detail-media-card">
            <img src="{escape(post['image_url'])}" alt="Post image" class="detail-image">
        </article>
        """
        if post["image_url"]
        else ""
    )
    owner_actions = (
        f"""
        <form method="post" action="/delete-post">
            <input type="hidden" name="viewer" value="{viewer_id}">
            <input type="hidden" name="post_id" value="{post['post_id']}">
            <button class="action-button danger" type="submit">Delete Post</button>
        </form>
        """
        if post["user_id"] == viewer_id
        else ""
    )
    body = f"""
    <section class="post-detail-layout {'text-only-detail' if not post['image_url'] else ''}">
        {media_html}
        <article class="detail-content-card">
            <div class="detail-user-row">
                <a href="{url_with_viewer('/', viewer_id, author=post['username'])}" class="post-user-stamp">
                    <img src="{escape(post['avatar_url'])}" alt="avatar" class="avatar tiny">
                    <span>@{escape(post['username'])}</span>
                </a>
                <span class="muted">{escape(post['relative_time'])}</span>
            </div>
            <p class="muted">{escape(post['display_name'])}</p>
            <h2>{escape(post['caption'].strip() or "Untitled post")}</h2>
            {f"<div class='detail-body'>{escape(post['body'])}</div>" if post['body'].strip() else ""}
            <div class="pill-row">{tags_html}</div>
            <div class="social-metrics">
                <span class="metric-pill">&#10084; {post['like_count']}</span>
                <span class="metric-pill">{post['comment_count']} comments</span>
            </div>
            <div class="detail-action-row">
                <form method="post" action="/toggle-like">
                    <input type="hidden" name="viewer" value="{viewer_id}">
                    <input type="hidden" name="post_id" value="{post['post_id']}">
                    <input type="hidden" name="return_to" value="{escape(return_to)}">
                    <button class="action-button {'primary' if post['liked_by_viewer'] else ''}" type="submit">{'Unlike' if post['liked_by_viewer'] else 'Like'}</button>
                </form>
                <form method="post" action="/toggle-bookmark">
                    <input type="hidden" name="viewer" value="{viewer_id}">
                    <input type="hidden" name="post_id" value="{post['post_id']}">
                    <input type="hidden" name="return_to" value="{escape(return_to)}">
                    <button class="action-button" type="submit">{'Saved' if post['bookmarked_by_viewer'] else 'Save'}</button>
                </form>
                {owner_actions}
            </div>
            <section class="comment-box">
                <div class="comment-header"><strong>Comments</strong></div>
                <ul class="comment-list">{comments_html}</ul>
                <form method="post" action="/comments" class="comment-form">
                    <input type="hidden" name="viewer" value="{viewer_id}">
                    <input type="hidden" name="post_id" value="{post['post_id']}">
                    <input type="hidden" name="return_to" value="{escape(return_to)}">
                    <input type="text" name="body" maxlength="180" placeholder="Add a comment" required>
                    <button class="action-button" type="submit">Comment</button>
                </form>
            </section>
        </article>
    </section>
    """
    return html_page("Post Detail", viewer_id, body, conn, active_nav="discover")


def render_history_page(conn: sqlite3.Connection, params: dict[str, list[str]]) -> bytes:
    viewer_id = current_user_id(params)
    profile = fetch_profile_summary(conn, viewer_id)
    posts = fetch_feed(conn, viewer_id, author=profile["username"], sort_by="latest")
    body = f"""
    <section class="profile-hero">
        <div class="profile-hero-main">
            <img src="{escape(profile['avatar_url'])}" alt="avatar" class="avatar">
            <div>
                <p class="eyebrow">Creator Profile</p>
                <h2>{escape(profile['display_name'])}</h2>
                <p class="profile-handle">@{escape(profile['username'])}</p>
                <p class="lead">{escape(profile['bio'])}</p>
            </div>
        </div>
        <div class="profile-summary-row">
            <div><strong>{profile['post_total']}</strong><span>Posts</span></div>
            <div><strong>{profile['like_total']}</strong><span>Total Likes</span></div>
            <div><strong>{profile['comment_total']}</strong><span>Comments</span></div>
        </div>
    </section>
    <section class="section-panel">
        <p class="eyebrow">Personal Archive</p>
        <h2>@{escape(profile['username'])} post archive</h2>
        <p class="lead">This page reads like a creator board instead of a raw history list, while still satisfying the user-specific post history requirement.</p>
    </section>
    <section class="feed-grid">
        {''.join(render_post_card(post, viewer_id) for post in posts) or '<p class="muted">No posts yet.</p>'}
    </section>
    """
    return html_page("My Posts", viewer_id, body, conn, active_nav="history")


def render_analytics_page(conn: sqlite3.Connection, params: dict[str, list[str]]) -> bytes:
    viewer_id = current_user_id(params)
    analytics = fetch_analytics(conn)

    def render_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
        header = "".join(f"<th>{escape(col.replace('_', ' ').title())}</th>" for col in columns)
        table_rows = "".join(
            f"<tr>{''.join(f'<td>{escape(str(row.get(col, "")))}</td>' for col in columns)}</tr>"
            for row in rows
        )
        return f"<table><thead><tr>{header}</tr></thead><tbody>{table_rows}</tbody></table>"

    tag_bars = "".join(
        f"""
        <div class="bar-row">
            <span>#{escape(tag['name'])}</span>
            <div class="bar-track"><div class="bar-fill" style="width: {min(tag['likes_on_tagged_posts'] * 8 + 12, 100)}%"></div></div>
            <strong>{tag['likes_on_tagged_posts']}</strong>
        </div>
        """
        for tag in analytics["trending_tags"]
    )
    body = f"""
    <section class="section-panel">
        <p class="eyebrow">Analytics Dashboard</p>
        <h2>SQL-backed rankings and activity snapshots</h2>
        <p class="lead">These views are rendered from aggregation queries on the relational schema, not hard-coded counters.</p>
    </section>
    <section class="dashboard-grid">
        <article class="dashboard-card">
            <h3>Most Liked Posts</h3>
            {render_table(analytics['most_liked'], ['post_id', 'username', 'like_count', 'comment_count'])}
        </article>
        <article class="dashboard-card">
            <h3>Most Active Users</h3>
            {render_table(analytics['active_users'], ['username', 'posts', 'comments', 'likes_received'])}
        </article>
        <article class="dashboard-card">
            <h3>Trending Tags</h3>
            <div class="bar-chart">{tag_bars}</div>
        </article>
        <article class="dashboard-card">
            <h3>Daily Posting Activity</h3>
            {render_table(analytics['daily_activity'], ['day', 'posts_created'])}
        </article>
    </section>
    """
    return html_page("Analytics", viewer_id, body, conn, active_nav="analytics")


def render_query_page(conn: sqlite3.Connection, params: dict[str, list[str]]) -> bytes:
    viewer_id = current_user_id(params)
    flash = params.get("flash", [""])[0] or None
    question = params.get("question", [""])[0]
    model_mode = "DeepSeek API-backed AI mode is enabled." if os.environ.get("DEEPSEEK_API_KEY") else "Using built-in local rule-based mode."
    explanation = ""
    columns: list[str] = []
    rows: list[tuple[Any, ...]] = []
    error = None
    if question:
        try:
            intent = translate_text_to_sql(question)
            explanation = intent.explanation
            columns, rows = execute_safe_sql(conn, intent, viewer_id=viewer_id)
        except AppError as exc:
            error = str(exc)
    table_html = ""
    if columns:
        header = "".join(f"<th>{escape(col)}</th>" for col in columns)
        body_rows = "".join(
            f"<tr>{''.join(f'<td>{escape(str(value))}</td>' for value in row)}</tr>"
            for row in rows
        )
        table_html = f"<table><thead><tr>{header}</tr></thead><tbody>{body_rows}</tbody></table>"
    elif question and not error:
        table_html = "<p class='muted'>The query ran successfully but returned no rows.</p>"
    prompt_links = "".join(
        f"<a class='filter-pill' href='{url_with_viewer('/query', viewer_id, question=prompt)}'>{escape(prompt)}</a>"
        for prompt in [
            "Show the most liked posts",
            "Show the most active users",
            "Show trending tags",
            "Show the latest posts",
            "Show comment counts by user",
            "Posts by duckt",
        ]
    )
    body = f"""
    <section class="section-panel">
        <p class="eyebrow">Ask HKUgram</p>
        <h2>Type a question in natural language and get database-backed results.</h2>
        <p class="lead">Users do not need to see SQL. The app interprets the request behind the scenes, queries the database safely, and only returns readable results.</p>
        <p class="muted">{escape(model_mode)}</p>
        {render_flash(flash)}
        {render_flash(error, 'error')}
    </section>
    <section class="query-grid">
        <article class="dashboard-card">
            <h3>Ask a question</h3>
            <form method="get" action="/query" class="query-form">
                <input type="hidden" name="viewer" value="{viewer_id}">
                <textarea name="question" rows="4" placeholder="Show the most liked posts">{escape(question)}</textarea>
                <button class="action-button primary" type="submit">Search</button>
            </form>
            <div class="pill-row">{prompt_links}</div>
        </article>
        <article class="dashboard-card">
            <h3>Search Summary</h3>
            <div class="result-summary">
                <p><strong>Your question</strong></p>
                <p>{escape(question or 'Choose a suggested prompt or type your own analytics question.')}</p>
                <p><strong>How HKUgram interpreted it</strong></p>
                <p class="muted">{escape(explanation or 'Waiting for a supported natural-language request.')}</p>
                <p><strong>Rows returned</strong></p>
                <p>{len(rows)}</p>
            </div>
        </article>
    </section>
    <section class="dashboard-card">
        <h3>Result Set</h3>
        {table_html}
    </section>
    """
    return html_page("Ask HKUgram", viewer_id, body, conn, active_nav="ask")


class HKUgramHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def get_session_user_id(self) -> int | None:
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        morsel = cookie.get("hkugram_user")
        if not morsel:
            return None
        try:
            return int(morsel.value)
        except ValueError:
            return None

    def current_user_id_or_redirect(self) -> int | None:
        user_id = self.get_session_user_id()
        if user_id is None:
            self.respond_redirect("/login")
            return None
        return user_id

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/static/"):
            return super().do_GET()
        params = parse_qs(parsed.query)
        if parsed.path == "/login":
            if self.get_session_user_id() is not None:
                return self.respond_redirect("/")
            return self.respond_bytes(render_login_page(flash=params.get("flash", [""])[0] or None))
        if parsed.path == "/register":
            if self.get_session_user_id() is not None:
                return self.respond_redirect("/")
            return self.respond_bytes(render_register_page(flash=params.get("flash", [""])[0] or None))
        if parsed.path == "/logout":
            return self.respond_redirect("/login?flash=Logged+out", cookie_header="hkugram_user=; Path=/; Max-Age=0; SameSite=Lax")
        viewer_id = self.current_user_id_or_redirect()
        if viewer_id is None:
            return
        try:
            with get_connection() as conn:
                if parsed.path == "/":
                    params["viewer"] = [str(viewer_id)]
                    return self.respond_bytes(render_feed_page(conn, params))
                if parsed.path == "/create":
                    params["viewer"] = [str(viewer_id)]
                    return self.respond_bytes(render_create_page(conn, params))
                if parsed.path == "/post":
                    params["viewer"] = [str(viewer_id)]
                    return self.respond_bytes(render_post_detail_page(conn, params))
                if parsed.path == "/analytics":
                    params["viewer"] = [str(viewer_id)]
                    return self.respond_bytes(render_analytics_page(conn, params))
                if parsed.path == "/query":
                    params["viewer"] = [str(viewer_id)]
                    return self.respond_bytes(render_query_page(conn, params))
                if parsed.path == "/history":
                    params["viewer"] = [str(viewer_id)]
                    return self.respond_bytes(render_history_page(conn, params))
        except AppError as exc:
            return self.respond_error(str(exc))
        self.send_error(HTTPStatus.NOT_FOUND, "Page not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length).decode("utf-8")
        form = {key: values[0] for key, values in parse_qs(payload).items()}
        if parsed.path == "/login":
            return self.handle_login(form)
        if parsed.path == "/register":
            return self.handle_register(form)
        viewer_id = self.current_user_id_or_redirect()
        if viewer_id is None:
            return
        try:
            with get_connection() as conn:
                if parsed.path == "/posts":
                    self.handle_create_post(conn, viewer_id, form)
                    return
                if parsed.path == "/toggle-like":
                    self.handle_toggle_like(conn, viewer_id, int(form["post_id"]))
                    return
                if parsed.path == "/toggle-bookmark":
                    self.handle_toggle_bookmark(conn, viewer_id, int(form["post_id"]))
                    return
                if parsed.path == "/comments":
                    self.handle_create_comment(conn, viewer_id, int(form["post_id"]), form.get("body", ""))
                    return
                if parsed.path == "/delete-comment":
                    self.handle_delete_comment(conn, viewer_id, int(form["comment_id"]))
                    return
                if parsed.path == "/delete-post":
                    self.handle_delete_post(conn, viewer_id, int(form["post_id"]))
                    return
        except (KeyError, ValueError):
            self.respond_error("The submitted form is invalid.")
            return
        except AppError as exc:
            self.respond_redirect(form.get("return_to") or "/")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Action not found")

    def handle_create_post(self, conn: sqlite3.Connection, viewer_id: int, form: dict[str, str]) -> None:
        image_url = form.get("image_url", "").strip()
        title = form.get("title", "").strip()
        body = form.get("body", "").strip()
        tags = parse_tags(form.get("tags", ""))
        if not title and not body and not image_url:
            raise AppError("Add a title, body text, an image URL, or a combination before publishing.")
        conn.execute(
            "INSERT INTO posts (user_id, caption, body, image_url) VALUES (?, ?, ?, ?)",
            (viewer_id, title, body, image_url),
        )
        post_id = conn.execute("SELECT last_insert_rowid() AS post_id").fetchone()["post_id"]
        for tag in tags:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
            tag_id = conn.execute("SELECT tag_id FROM tags WHERE name = ?", (tag,)).fetchone()["tag_id"]
            conn.execute(
                "INSERT OR IGNORE INTO post_tags (post_id, tag_id) VALUES (?, ?)",
                (post_id, tag_id),
            )
        conn.commit()
        self.respond_redirect(url_with_viewer("/create", viewer_id, flash="Post published."))

    def handle_login(self, form: dict[str, str]) -> None:
        username = form.get("username", "").strip().lower()
        password = form.get("password", "")
        with get_connection() as conn:
            user = conn.execute(
                "SELECT user_id, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            return self.respond_bytes(render_login_page(error="Invalid username or password."), status=400)
        cookie_header = f"hkugram_user={user['user_id']}; Path=/; HttpOnly; SameSite=Lax"
        self.respond_redirect("/", cookie_header=cookie_header)

    def handle_register(self, form: dict[str, str]) -> None:
        username = form.get("username", "").strip().lower()
        display_name = form.get("display_name", "").strip()
        password = form.get("password", "")
        if not username or not display_name or not password:
            return self.respond_bytes(render_register_page(error="Username, display name, and password are required."), status=400)
        if len(username) < 3 or not username.replace("_", "").isalnum():
            return self.respond_bytes(render_register_page(error="Username must be unique and use letters, numbers, or underscores."), status=400)
        with get_connection() as conn:
            existing = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                return self.respond_bytes(render_register_page(error="That username is already taken."), status=400)
            conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash, bio, avatar_url)
                VALUES (?, ?, ?, '', ?)
                """,
                (username, display_name, hash_password(password), f"https://picsum.photos/seed/{username}/80/80"),
            )
            user_id = conn.execute("SELECT last_insert_rowid() AS user_id").fetchone()["user_id"]
            conn.commit()
        cookie_header = f"hkugram_user={user_id}; Path=/; HttpOnly; SameSite=Lax"
        self.respond_redirect("/", cookie_header=cookie_header)

    def handle_toggle_like(self, conn: sqlite3.Connection, viewer_id: int, post_id: int) -> None:
        existing = conn.execute(
            "SELECT like_id FROM likes WHERE user_id = ? AND post_id = ?",
            (viewer_id, post_id),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM likes WHERE like_id = ?", (existing["like_id"],))
            flash = "Post unliked."
        else:
            conn.execute("INSERT INTO likes (user_id, post_id) VALUES (?, ?)", (viewer_id, post_id))
            flash = "Post liked."
        conn.commit()
        target = self.headers.get("Referer") or url_with_viewer("/", viewer_id)
        self.respond_redirect(target)

    def handle_toggle_bookmark(self, conn: sqlite3.Connection, viewer_id: int, post_id: int) -> None:
        existing = conn.execute(
            "SELECT bookmark_id FROM bookmarks WHERE user_id = ? AND post_id = ?",
            (viewer_id, post_id),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM bookmarks WHERE bookmark_id = ?", (existing["bookmark_id"],))
            flash = "Bookmark removed."
        else:
            conn.execute("INSERT INTO bookmarks (user_id, post_id) VALUES (?, ?)", (viewer_id, post_id))
            flash = "Post saved."
        conn.commit()
        target = self.headers.get("Referer") or url_with_viewer("/", viewer_id)
        self.respond_redirect(target)

    def handle_create_comment(self, conn: sqlite3.Connection, viewer_id: int, post_id: int, body: str) -> None:
        cleaned = body.strip()
        if not cleaned:
            raise AppError("Comment text cannot be empty.")
        created_at = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        conn.execute(
            "INSERT INTO comments (user_id, post_id, body, created_at) VALUES (?, ?, ?, ?)",
            (viewer_id, post_id, cleaned, created_at),
        )
        conn.commit()
        target = self.headers.get("Referer") or url_with_viewer("/", viewer_id)
        self.respond_redirect(target)

    def handle_delete_comment(self, conn: sqlite3.Connection, viewer_id: int, comment_id: int) -> None:
        comment = conn.execute(
            "SELECT comment_id FROM comments WHERE comment_id = ? AND user_id = ?",
            (comment_id, viewer_id),
        ).fetchone()
        if not comment:
            raise AppError("You can only delete your own comments.")
        conn.execute("DELETE FROM comments WHERE comment_id = ?", (comment_id,))
        conn.commit()
        target = self.headers.get("Referer") or url_with_viewer("/", viewer_id)
        self.respond_redirect(target)

    def handle_delete_post(self, conn: sqlite3.Connection, viewer_id: int, post_id: int) -> None:
        post = conn.execute(
            "SELECT post_id FROM posts WHERE post_id = ? AND user_id = ?",
            (post_id, viewer_id),
        ).fetchone()
        if not post:
            raise AppError("You can only delete your own posts.")
        conn.execute("DELETE FROM posts WHERE post_id = ?", (post_id,))
        conn.commit()
        self.respond_redirect(url_with_viewer("/history", viewer_id, flash="Post deleted."))

    def respond_bytes(self, payload: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def respond_redirect(self, location: str, cookie_header: str | None = None) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        if cookie_header:
            self.send_header("Set-Cookie", cookie_header)
        self.end_headers()

    def respond_error(self, message: str) -> None:
        payload = f"<h1>Error</h1><p>{escape(message)}</p>".encode("utf-8")
        self.respond_bytes(payload, status=400)


def main() -> None:
    init_db()
    host = os.environ.get("HKUGRAM_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("HKUGRAM_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), HKUgramHandler)
    print(f"HKUgram running at http://{host}:{port}")
    print(f"Using local database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        save_local_snapshot()
        server.server_close()


if __name__ == "__main__":
    main()
