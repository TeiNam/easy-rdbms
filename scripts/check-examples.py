#!/usr/bin/env python3
"""Execute the documented regression examples in disposable databases.

Requires Docker, Django 5.2, and psycopg 3. Run: python scripts/check-examples.py
Only containers created here are changed or removed. PostgreSQL is exposed on a random
loopback port for the real Django/concurrency checks; MySQL has no external network.
"""

import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
CLIENTS = {}


def block(path, needle):
    matches = [
        code for code in re.findall(r"```(?:sql|python)\n(.*?)\n```", (ROOT / path).read_text(), re.S)
        if needle in code
    ]
    assert len(matches) == 1, (path, needle, len(matches))
    return matches[0]


def run(args, text="", **kwargs):
    return subprocess.run(args, input=text, text=True, capture_output=True, timeout=90, **kwargs)


def sql(engine, text, error=None):
    result = run(CLIENTS[engine], text)
    if error is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0 and error in result.stderr, result.stdout + result.stderr
    return result.stdout.strip()


@contextmanager
def databases():
    owned = []
    password = secrets.token_hex(16)
    try:
        for engine, image, data_dir, memory, options, client in [
            ("pg", "postgres:16-alpine", "/var/lib/postgresql/data", "512m",
             ["-e", "POSTGRES_DB=example_check", "-e", f"POSTGRES_PASSWORD={password}",
              "-p", "127.0.0.1::5432"],
             ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "example_check"]),
            ("mysql", "mysql:8.4", "/var/lib/mysql", "768m",
             ["--network", "none", "-e", "MYSQL_DATABASE=example_check",
              "-e", "MYSQL_ALLOW_EMPTY_PASSWORD=1"],
             ["mysql", "--protocol=TCP", "-h", "127.0.0.1", "-u", "root",
              "--batch", "--raw", "--skip-column-names", "example_check"]),
        ]:
            cid = run([
                "docker", "run", "--rm", "-d", "--name", f"easy-rdbms-smoke-{engine}-{secrets.token_hex(4)}",
                "--memory", memory, "--cpus", "1", "--tmpfs", data_dir,
                *options, f"public.ecr.aws/docker/library/{image}",
            ], check=True).stdout.strip()
            owned.append(cid)
            CLIENTS[engine] = ["docker", "exec", "-i", cid, *client]
            deadline = time.monotonic() + 60
            while run(CLIENTS[engine], "SELECT 1;").returncode:
                if time.monotonic() >= deadline:
                    raise RuntimeError(run(["docker", "logs", cid]).stdout)
                time.sleep(0.25)
            print(f"READY {engine}: {sql(engine, 'SELECT version();')}", flush=True)
        port = run(["docker", "port", owned[0], "5432/tcp"], check=True).stdout.strip().rsplit(":", 1)[1]
        yield dict(host="127.0.0.1", port=int(port), user="postgres",
                   password=password, dbname="example_check")
    finally:
        if owned:
            run(["docker", "stop", "--timeout", "5", *owned], check=True)
            print("CLEANUP: disposable database containers removed", flush=True)


def metadata():
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        for code in re.findall(r"```python\n(.*?)\n```", path.read_text(), re.S):
            ast.parse(code, filename=str(path))
    for path in [*ROOT.glob(".*-plugin/*.json"), *ROOT.glob(".agents/plugins/*.json")]:
        json.loads(path.read_text())
    versions = {
        json.loads((ROOT / path).read_text())["version"]
        for path in [".claude-plugin/plugin.json", ".codex-plugin/plugin.json"]
    }
    assert len(versions) == 1, versions
    version = versions.pop()
    readme = (ROOT / "README.md").read_text()
    assert f"Current: **{version}**" in readme
    assert f"현재 배포 버전은 **{version}**" in readme
    for path in ROOT.glob("skills/*/SKILL.md"):
        header = path.read_text().split("---", 2)[1]
        assert set(re.findall(r"^([\w-]+):", header, re.M)) == {"name", "description"}, path
        description = header.split("description:", 1)[1].strip().lstrip(">").strip()
        assert len(" ".join(description.split())) <= 1024, path


def sqlite_and_sync():
    with sqlite3.connect(":memory:") as db:
        db.executescript(block("skills/sqlite-guideline/SKILL.md", "CREATE TABLE member ("))
        db.execute("INSERT INTO member(email) VALUES ('first@example.test')")
        db.execute("INSERT INTO member(member_id,email) VALUES (99,'second@example.test')")
        assert db.execute("SELECT rowid,member_id FROM member ORDER BY member_id").fetchall() == [(1, 1), (99, 99)]
        db.execute("CREATE TABLE named_pk(id INTEGER, CONSTRAINT pk_named_pk PRIMARY KEY(id)) STRICT")
        db.execute("INSERT INTO named_pk DEFAULT VALUES")
        assert db.execute("SELECT rowid,id FROM named_pk").fetchone() == (1, 1)
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        plugin, harness = base / "plugin", base / "harness"
        (plugin / "scripts").mkdir(parents=True)
        shutil.copy2(ROOT / "scripts/sync-from-harness.sh", plugin / "scripts")
        skills = ["rdbms-naming", "mysql-guideline", "postgres-guideline", "database-migrations"]
        for skill in skills:
            for parent, content in [(plugin, "local"), (harness, "upstream")]:
                path = parent / "skills" / skill
                path.mkdir(parents=True)
                (path / "SKILL.md").write_text(content)
        args = ["sh", str(plugin / "scripts/sync-from-harness.sh")]
        env = dict(os.environ, HARNESS=str(harness))
        run(args, env=env, check=True)
        assert (plugin / "skills/rdbms-naming/SKILL.md").read_text() == "local"
        run([*args, "--apply"], env=env, check=True)
        assert all((plugin / "skills" / skill / "SKILL.md").read_text() == "upstream" for skill in skills)


def pg_cutover():
    path = "skills/database-migrations/SKILL.md"
    preparation = block(path, "CREATE UNIQUE INDEX CONCURRENTLY uq_chat_history_id_new")
    cutover = block(path, "PRIMARY KEY USING INDEX uq_chat_history_id_new")
    for old_id in [2147483647, None]:
        sql("pg", """
            DROP SCHEMA IF EXISTS log CASCADE; CREATE SCHEMA log;
            CREATE TABLE log.chat_history (
              chat_history_id int GENERATED ALWAYS AS IDENTITY,
              chat_history_id_new bigint, body text NOT NULL DEFAULT 'test',
              CONSTRAINT pk_chat_history PRIMARY KEY (chat_history_id));
        """)
        if old_id:
            sql("pg", f"""
                INSERT INTO log.chat_history(chat_history_id,chat_history_id_new)
                  OVERRIDING SYSTEM VALUE VALUES ({old_id},{old_id});
                CREATE TABLE log.child(parent_id bigint REFERENCES log.chat_history(chat_history_id));
                INSERT INTO log.child VALUES ({old_id});
            """)
        sql("pg", preparation)
        if old_id:
            sql("pg", """
                ALTER TABLE log.child ADD CONSTRAINT fk_child_new
                  FOREIGN KEY(parent_id) REFERENCES log.chat_history(chat_history_id_new) NOT VALID;
                ALTER TABLE log.child VALIDATE CONSTRAINT fk_child_new;
                ALTER TABLE log.child DROP CONSTRAINT child_parent_id_fkey;
            """)
        sql("pg", cutover)
        expected = old_id + 1 if old_id else 1
        assert sql("pg", """
            INSERT INTO log.chat_history(body) VALUES ('after cutover')
            RETURNING chat_history_id, chat_history_id_old IS NULL;
        """) == f"{expected}|t"
        assert sql("pg", "SELECT count(*) FROM pg_index WHERE indrelid='log.chat_history'::regclass AND indisunique;") == "1"
        if old_id:
            sql("pg", f"INSERT INTO log.child VALUES ({expected});")


def pg_backfill(config):
    import psycopg
    sql("pg", """
        CREATE TABLE member(member_id int PRIMARY KEY, email text NOT NULL, normalized_email text);
        INSERT INTO member VALUES (1,'A@EXAMPLE.TEST',NULL),(2,'B@EXAMPLE.TEST',NULL);
    """)
    code = block("skills/database-migrations/SKILL.md", "DO $$").split("DO $$", 1)[1]
    code = "DO $$" + code  # Leave the deliberately bad unbatched example above the DO unexecuted.
    with psycopg.connect(**config) as holder:
        holder.execute("SELECT member_id FROM member WHERE member_id=1 FOR UPDATE").fetchone()
        sql("pg", code, error="Backfill incomplete")
        assert sql("pg", "SELECT normalized_email FROM member WHERE member_id=2;") == "b@example.test"
    sql("pg", code)
    assert sql("pg", "SELECT count(*) FROM member WHERE normalized_email IS NULL;") == "0"


def showcase():
    sql("pg", "DROP SCHEMA IF EXISTS app CASCADE; DROP SCHEMA IF EXISTS log CASCADE;")
    sql("pg", block("docs/with-and-without.md", "CREATE SCHEMA app"))
    sql("pg", """
        INSERT INTO app.member(public_id,email,password_hash)
          VALUES ('00000000-0000-7000-8000-000000000001','a@example.test','test-only');
        INSERT INTO app.conversation(member_id) VALUES (1);
        INSERT INTO log.message(conversation_id,message_role,content) VALUES (1,'user','now');
        INSERT INTO log.message(conversation_id,message_role,content,created_at)
          VALUES (1,'user','past','1900-01-01'),(1,'user','future','2200-01-01');
    """)
    assert sql("pg", "SELECT count(*) FROM log.message;") == "3"
    for role, tokens, constraint in [("invalid", 0, "chk_message_role"), ("user", -1, "chk_message_token_count")]:
        sql("pg", f"""INSERT INTO log.message(conversation_id,message_role,content,token_count)
                     VALUES (1,'{role}','bad',{tokens});""", error=constraint)


def partitions_and_subtypes():
    path = "skills/postgres-guideline/partitioning.md"
    sql("pg", "DROP SCHEMA log CASCADE; CREATE SCHEMA log;")
    sql("pg", block(path, "CREATE TABLE log.chat_history ("))
    sql("pg", """
        INSERT INTO log.chat_history(conversation_id,member_id,user_message,bot_response,created_at)
        VALUES ('conv',1,'q','a','2026-10-15'),('conv',1,'q','a','1900-01-01');
    """)
    sql("pg", block(path, "-- PASS: Correct sequence"))
    assert sql("pg", "SELECT count(*) FROM log.chat_history;") == "2"
    assert sql("pg", "SELECT count(*) FROM log.chat_history_2026_10;") == "1"
    future = block(path, "-- Prepare the future November partition")
    future = future.replace("COMMIT;", """
        SELECT mode FROM pg_locks WHERE relation='log.chat_history'::regclass AND pid=pg_backend_pid();
        COMMIT;
    """)
    locks = sql("pg", future)
    assert "ShareUpdateExclusiveLock" in locks and "AccessExclusiveLock" not in locks, locks
    sql("pg", """
        INSERT INTO log.chat_history(conversation_id,member_id,user_message,bot_response,created_at)
        VALUES ('conv',1,'q','a','2026-11-15');
    """)
    assert sql("pg", "SELECT count(*) FROM log.chat_history_2026_11;") == "1"
    sql("pg", block("skills/rdbms-modeling/references/generalization.md", "-- PostgreSQL: enforce exclusivity"))
    sql("pg", """
        INSERT INTO customer(customer_type) VALUES ('INDIVIDUAL');
        INSERT INTO individual_customer(customer_id,birth_date) VALUES (1,'2000-01-01');
    """)
    sql("pg", """INSERT INTO corporate_customer(customer_id,business_registration_number)
                 VALUES (1,'test');""", error="fk_corporate_customer_customer")
    sql("pg", """
        CREATE TABLE partition_child(customer_id int, created_at date) PARTITION BY RANGE(created_at);
        CREATE TABLE partition_child_default PARTITION OF partition_child DEFAULT;
    """)
    sql("pg", """ALTER TABLE partition_child ADD CONSTRAINT fk_partition_child
                 FOREIGN KEY(customer_id) REFERENCES customer(customer_id) NOT VALID;""",
        error="cannot add NOT VALID foreign key on partitioned table")
    sql("pg", """ALTER TABLE partition_child ADD CONSTRAINT fk_partition_child
                 FOREIGN KEY(customer_id) REFERENCES customer(customer_id);""")


def parent_locks(config):
    import psycopg
    code = block("skills/postgres-guideline/schema-design.md", "async def create_chat_history")
    calls = sorted(
        (node for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Call)
         and isinstance(node.func, ast.Attribute) and node.func.attr == "execute"),
        key=lambda node: node.lineno,
    )
    queries = [ast.literal_eval(call.args[0]) for call in calls[:2]]
    sql("pg", """CREATE TABLE app.conversation_session(conversation_id char(18) PRIMARY KEY);
                 INSERT INTO app.conversation_session VALUES ('conv');""")
    with psycopg.connect(**config) as first, psycopg.connect(**config) as second:
        second.execute("SET lock_timeout='200ms'")
        for connection in [first, second]:
            for query in queries:
                assert connection.execute(query, dict(member_id=1, cid="conv")).fetchone()
        second.commit()  # Sibling checks succeeded while first still holds both locks.
        try:
            second.execute("UPDATE app.member SET is_active=false WHERE member_id=1")
        except psycopg.errors.LockNotAvailable:
            second.rollback()
        else:
            raise AssertionError("The member's active-state guard did not block its modification")


def mysql_examples():
    sql("mysql", block("skills/mysql-guideline/schema-design.md", "CREATE TABLE `member`"))
    sql("mysql", "INSERT INTO member(email,is_active) VALUES ('zero',0),('one',1);")
    sql("mysql", "INSERT INTO member(email,is_active) VALUES ('two',2);", error="chk_member_is_active")
    sql("mysql", "INSERT INTO member(email,is_active) VALUES ('negative',-5);", error="Out of range")
    sql("mysql", """
        CREATE TABLE chat_history(chat_history_id int unsigned NOT NULL AUTO_INCREMENT PRIMARY KEY,
          chat_history_id_new bigint unsigned NOT NULL, body text);
        INSERT INTO chat_history VALUES (4294967295,4294967295,'before');
        CREATE UNIQUE INDEX uq_chat_history_id_new ON chat_history(chat_history_id_new);
        CREATE TABLE chat_reference(parent_id bigint unsigned NOT NULL,
          CONSTRAINT fk_chat_reference_history FOREIGN KEY(parent_id)
            REFERENCES chat_history(chat_history_id_new));
        INSERT INTO chat_reference VALUES (4294967295);
    """)
    path = "skills/database-migrations/SKILL.md"
    sql("mysql", block(path, "DROP FOREIGN KEY fk_chat_reference_history"))
    sql("mysql", block(path, "CHANGE chat_history_id chat_history_id_old"))
    sql("mysql", block(path, "ADD CONSTRAINT fk_chat_reference_history"))
    sql("mysql", "INSERT INTO chat_history(body) VALUES ('after');")
    assert sql("mysql", "SELECT chat_history_id,chat_history_id_old IS NULL FROM chat_history WHERE body='after';") == "4294967296\t1"
    assert sql("mysql", """SELECT count(DISTINCT index_name) FROM information_schema.statistics
                          WHERE table_schema=DATABASE() AND table_name='chat_history' AND non_unique=0;""") == "1"
    sql("mysql", "INSERT INTO chat_reference VALUES (4294967296);")
    sql("mysql", "DROP TABLE chat_reference; DROP TABLE chat_history;")
    sql("mysql", block("skills/mysql-guideline/partitioning.md", "PARTITION BY RANGE COLUMNS (created_at) ("))
    sql("mysql", block("skills/mysql-guideline/partitioning.md", "ALGORITHM=INPLACE, DROP PARTITION"))
    sql("mysql", """
        CREATE TABLE product(product_id int PRIMARY KEY, name varchar(30) NOT NULL, created_at datetime NOT NULL);
        SET SESSION cte_max_recursion_depth=100001;
        INSERT INTO product
        WITH RECURSIVE n AS (SELECT 1 AS i UNION ALL SELECT i+1 FROM n WHERE i<100000)
        SELECT i,CONCAT('p',i),TIMESTAMP('2026-01-01')+INTERVAL FLOOR((i-1)/10) SECOND FROM n;
    """)
    code = block("skills/mysql-guideline/operations.md", "SELECT product_id, name, created_at")
    select, index = code.split("CREATE INDEX", 1)
    sql("mysql", "CREATE INDEX" + index)
    for value in ["'2026-01-01 00:16:39'", "'2026-01-01 00:16:39'", "9996"]:
        select = select.replace("?", value, 1)
    plan = sql("mysql", "EXPLAIN ANALYZE " + select)
    assert "Index range scan" in plan, plan
    rows = sql("mysql", select).splitlines()
    assert [int(row.split("\t")[0]) for row in rows] == list(range(9995, 9945, -1)), rows
    assert "rows=50 loops=1" in plan, plan
    print(plan, flush=True)


def django_backfill(config):
    import django
    from django.conf import settings
    from django.db import connections, models
    from django.db.migrations.state import ModelState, ProjectState
    sql("pg", "CREATE DATABASE other_check;")
    db = dict(ENGINE="django.db.backends.postgresql", NAME=config["dbname"], USER=config["user"],
              PASSWORD=config["password"], HOST=config["host"], PORT=config["port"])
    settings.configure(INSTALLED_APPS=[], USE_TZ=True, DATABASES={
        "default": db, "other": dict(db, NAME="other_check"), "writer": dict(db, NAME="other_check"),
    })
    django.setup()
    state = ProjectState()
    state.add_model(ModelState("accounts", "Member", [
        ("id", models.AutoField(primary_key=True)),
        ("username", models.CharField(max_length=64)),
        ("display_name", models.CharField(max_length=64, default="")),
    ]))
    Member = state.apps.get_model("accounts", "Member")
    try:
        for alias in ["default", "other"]:
            with connections[alias].schema_editor() as editor:
                editor.create_model(Member)
        Member.objects.using("default").create(username="default_original")
        members = Member.objects.using("other")
        race = members.create(username="race_original")
        existing = members.create(username="existing_original", display_name="existing_choice")
        members.bulk_create([Member(username=f"user_{i}") for i in range(5001)])
        namespace = {}
        exec(block("skills/database-migrations/SKILL.md", "def backfill_display_names"), namespace)
        updates = 0

        def interleave(execute, statement, params, many, context):
            nonlocal updates
            if statement.lstrip().upper().startswith("UPDATE"):
                if updates == 0:
                    # A separate connection commits after the batch SELECT and before its UPDATE.
                    with connections["writer"].cursor() as cursor:
                        cursor.execute("SET statement_timeout='2s'")
                    Member.objects.using("writer").filter(pk=race.pk).update(display_name="user_choice")
                else:
                    # The previous batch must already be visible to another connection.
                    assert Member.objects.using("writer").get(username="user_0").display_name == "user_0"
                updates += 1
            return execute(statement, params, many, context)

        with connections["other"].execute_wrapper(interleave):
            migration = namespace["Migration"]("backfill_display_names", "accounts")
            with connections["other"].schema_editor(atomic=migration.atomic) as editor:
                migration.apply(state, editor)
        assert Member.objects.using("default").get().display_name == ""
        assert members.get(pk=race.pk).display_name == "user_choice"
        assert members.get(pk=existing.pk).display_name == "existing_choice"
        assert not members.filter(display_name="").exists()
        assert not members.exclude(pk__in=[race.pk, existing.pk]).exclude(display_name=models.F("username")).exists()
        assert updates == 2, updates
        print(f"Django {django.get_version()}: target alias, concurrent writer, two committed batches verified", flush=True)
    finally:
        connections.close_all()


if __name__ == "__main__":
    import django  # Fail before starting containers if test dependencies are missing.
    import psycopg
    for check in [metadata, sqlite_and_sync]:
        check()
        print(f"PASS {check.__name__}", flush=True)
    with databases() as config:
        for check, args in [
            (pg_cutover, ()), (pg_backfill, (config,)), (showcase, ()),
            (partitions_and_subtypes, ()), (parent_locks, (config,)),
            (mysql_examples, ()), (django_backfill, (config,)),
        ]:
            check(*args)
            print(f"PASS {check.__name__}", flush=True)
