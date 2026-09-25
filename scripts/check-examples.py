#!/usr/bin/env python3
"""Execute the documented regression examples in disposable databases.

Requires Docker, OpenSSL, Django 5.2, and psycopg 3. Run: python scripts/check-examples.py
Default: PostgreSQL 18 / MySQL 8.4. --pg-major 16 checks compatibility.
--extensions uses scripts/Dockerfile.postgres built as easy-rdbms-examples-pg<major>.
Only containers created here are changed or removed. PostgreSQL is exposed on a random
loopback port for the real Django/concurrency checks; MySQL has no external network.
"""

import argparse
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
def databases(pg_major=18, extensions=False):
    owned = []
    password = secrets.token_hex(16)
    pg_image = (f"easy-rdbms-examples-pg{pg_major}" if extensions else
                f"public.ecr.aws/docker/library/postgres:{pg_major}-{'bookworm' if pg_major >= 18 else 'alpine'}")
    if extensions:
        assert run(["docker", "image", "inspect", pg_image]).returncode == 0, (
            f"Build first: docker build -f scripts/Dockerfile.postgres "
            f"--build-arg PG_MAJOR={pg_major} -t {pg_image} ."
        )
    try:
        for engine, image, data_dir, memory, options, client in [
            ("pg", pg_image, "/var/lib/postgresql" if pg_major >= 18 else "/var/lib/postgresql/data", "512m",
             ["-e", "POSTGRES_DB=example_check", "-e", f"POSTGRES_PASSWORD={password}",
              "-e", "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256",
              "-p", "127.0.0.1::5432"],
             ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "example_check"]),
            ("mysql", "public.ecr.aws/docker/library/mysql:8.4", "/var/lib/mysql", "768m",
             ["--network", "none", "-e", "MYSQL_DATABASE=example_check",
              "-e", "MYSQL_ALLOW_EMPTY_PASSWORD=1"],
             ["mysql", "--protocol=TCP", "-h", "127.0.0.1", "-u", "root",
              "--batch", "--raw", "--skip-column-names", "example_check"]),
        ]:
            cid = run([
                "docker", "run", "--rm", "-d", "--name", f"easy-rdbms-smoke-{engine}-{secrets.token_hex(4)}",
                "--memory", memory, "--cpus", "1", "--tmpfs", data_dir,
                *options, image,
                *(["-c", "shared_preload_libraries=pg_stat_statements"] if engine == "pg" else []),
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
    # 스킬과 상세 문서의 참조는 같은 폴더 또는 skills/ 기준으로 해석한다.
    for path in ROOT.glob("skills/**/*.md"):
        for target in re.findall(r"`([^`\n]+\.md)`", path.read_text()):
            assert any(candidate.is_file() for candidate in [
                path.parent / target, ROOT / "skills" / target, ROOT / target,
            ]), (path.relative_to(ROOT), target)


def sqlite_and_sync():
    with sqlite3.connect(":memory:") as db:
        db.executescript(block("skills/sqlite-guideline/SKILL.md", "CREATE TABLE member ("))
        db.execute("INSERT INTO member(email) VALUES ('first@example.test')")
        db.execute("INSERT INTO member(member_id,email) VALUES (99,'second@example.test')")
        assert db.execute("SELECT rowid,member_id FROM member ORDER BY member_id").fetchall() == [(1, 1), (99, 99)]
        db.execute("CREATE TABLE named_pk(id INTEGER, CONSTRAINT pk_named_pk PRIMARY KEY(id)) STRICT")
        db.execute("INSERT INTO named_pk DEFAULT VALUES")
        assert db.execute("SELECT rowid,id FROM named_pk").fetchone() == (1, 1)
        if sqlite3.sqlite_version_info >= (3, 45):
            db.executescript(block("skills/sqlite-guideline/SKILL.md", "CREATE TABLE local_payload"))
            assert db.execute("SELECT typeof(payload),json_extract(payload,'$.type') FROM local_payload").fetchone() == ("blob", "message")
            try:
                db.execute("INSERT INTO local_payload(payload) VALUES (x'000102')")
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("Invalid JSONB was accepted")
        else:
            print("SKIP SQLite JSONB: requires 3.45+", flush=True)
        if sqlite3.sqlite_version_info >= (3, 46):
            db.execute("PRAGMA optimize=0x10002")
            db.execute("PRAGMA optimize")
        else:
            print("SKIP modern PRAGMA optimize: requires 3.46+", flush=True)
        print(f"SQLite {sqlite3.sqlite_version}: rowid, JSONB and optimize version gates checked", flush=True)
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
    constraint = """ALTER TABLE partition_child ADD CONSTRAINT fk_partition_child
                    FOREIGN KEY(customer_id) REFERENCES customer(customer_id)"""
    if int(sql("pg", "SHOW server_version_num;")) >= 180000:
        sql("pg", "INSERT INTO partition_child VALUES (-1,'2026-09-01');")
        sql("pg", constraint + " NOT VALID;")
        sql("pg", "INSERT INTO partition_child VALUES (-2,'2026-09-01');", error="fk_partition_child")
        sql("pg", "ALTER TABLE partition_child VALIDATE CONSTRAINT fk_partition_child;", error="fk_partition_child")
        sql("pg", "DELETE FROM partition_child WHERE customer_id=-1;")
        sql("pg", "ALTER TABLE partition_child VALIDATE CONSTRAINT fk_partition_child;")
        assert sql("pg", "SELECT bool_and(convalidated) FROM pg_constraint WHERE conname='fk_partition_child';") == "t"
    else:
        sql("pg", constraint + " NOT VALID;", error="cannot add NOT VALID foreign key on partitioned table")
        sql("pg", constraint + ";")


def pg_version_and_rls(config):
    import psycopg
    if int(sql("pg", "SHOW server_version_num;")) >= 180000:
        path = "skills/postgres-guideline/version-and-upgrade.md"
        sql("pg", block(path, "CREATE TABLE app.catalog_item"))
        sql("pg", "INSERT INTO app.catalog_item(quantity,unit_price) VALUES (2,1.50);")
        assert sql("pg", "SELECT uuid_extract_version(catalog_item_id),total_price FROM app.catalog_item;") == "7|3.00"
        assert sql("pg", "SELECT attgenerated FROM pg_attribute WHERE attrelid='app.catalog_item'::regclass AND attname='total_price';") == "v"
        sql("pg", block(path, "SHOW io_method"))
        sql("pg", """CREATE FUNCTION app.plus_one(integer) RETURNS integer
                    LANGUAGE sql IMMUTABLE AS 'SELECT $1+1';""")
        sql("pg", """ALTER TABLE app.catalog_item ADD COLUMN invalid_virtual int
                    GENERATED ALWAYS AS (app.plus_one(quantity)) VIRTUAL;""",
            error="user-defined function")
        sql("pg", "DROP TABLE app.catalog_item; DROP FUNCTION app.plus_one(integer);")
    else:
        sql("pg", "SELECT uuidv7();", error="function uuidv7() does not exist")
        sql("pg", """CREATE TABLE virtual_probe(n int, doubled int
                    GENERATED ALWAYS AS (n*2) VIRTUAL);""", error="syntax error")
    # 문서의 RLS 정책을 비소유자 역할과 재사용하는 한 연결에서 실행한다.
    sql("pg", """CREATE TABLE app.purchase_order(
                  purchase_order_id bigint GENERATED ALWAYS AS IDENTITY,
                  member_id int, created_at timestamptz NOT NULL DEFAULT now());
                INSERT INTO app.purchase_order(member_id) VALUES (1),(2);""")
    sql("pg", block("skills/postgres-guideline/schema-design.md", "CREATE POLICY member_orders"))
    sql("pg", block("skills/rdbms-modeling/references/views-and-materialized-views.md", "CREATE VIEW app.member_order"))
    sql("pg", """GRANT USAGE ON SCHEMA app TO app_runtime;
                GRANT SELECT ON app.member_order TO app_runtime;
                GRANT SELECT,INSERT ON app.purchase_order TO app_runtime;""")
    with psycopg.connect(**config, autocommit=True) as conn:
        conn.execute("SET ROLE app_runtime")
        assert conn.execute("SELECT member_id FROM app.purchase_order").fetchall() == []
        assert conn.execute("SELECT member_id FROM app.member_order").fetchall() == []
        for member in ["1", "2"]:
            with conn.transaction():
                conn.execute("SELECT set_config('app.current_member_id', %s, true)", (member,))
                assert conn.execute("SELECT member_id FROM app.purchase_order").fetchall() == [(int(member),)]
                assert conn.execute("SELECT member_id FROM app.member_order").fetchall() == [(int(member),)]
                try:
                    with conn.transaction():
                        conn.execute("INSERT INTO app.purchase_order(member_id) VALUES (99)")
                except psycopg.errors.InsufficientPrivilege:
                    pass
                else:
                    raise AssertionError("RLS accepted another member's row")
            assert conn.execute("SELECT member_id FROM app.purchase_order").fetchall() == []
            assert conn.execute("SELECT member_id FROM app.member_order").fetchall() == []
    sql("pg", "DROP VIEW app.member_order; DROP TABLE app.purchase_order;")


def pg_builtin_extensions():
    path = "skills/postgres-guideline/extensions.md"
    sql("pg", block(path, "SELECT name, default_version"))
    sql("pg", block(path, "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
    assert int(sql("pg", "SELECT count(*) FROM pg_stat_statements;")) > 0
    sql("pg", """CREATE TABLE app.catalog_label(catalog_label_id int PRIMARY KEY,label text);
                INSERT INTO app.catalog_label VALUES (1,'서울시청 안내'),(2,'부산시청 안내');""")
    query = block(path, "CREATE INDEX idx_catalog_label_label_trgm")
    sql("pg", query)
    result = query.split("EXPLAIN (ANALYZE, BUFFERS)", 1)[1]
    assert sql("pg", result) == "1|서울시청 안내"
    sql("pg", "DROP TABLE app.catalog_label;")


def pg_fdw():
    cid = CLIENTS["pg"][3]
    # 임시 CA 겸 서버 인증서로 문서의 verify-full 연결을 그대로 검사한다.
    with tempfile.TemporaryDirectory() as directory:
        cert, key = Path(directory) / "fdw.crt", Path(directory) / "fdw.key"
        run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert)], check=True)
        for path in [cert, key]:
            run(["docker", "cp", str(path), f"{cid}:/tmp/{path.name}"], check=True)
        run(["docker", "exec", "-u", "0", cid, "chown", "postgres:postgres",
             "/tmp/fdw.crt", "/tmp/fdw.key"], check=True)
        run(["docker", "exec", "-u", "0", cid, "chmod", "600", "/tmp/fdw.key"], check=True)
    sql("pg", """ALTER SYSTEM SET ssl_cert_file='/tmp/fdw.crt';
                ALTER SYSTEM SET ssl_key_file='/tmp/fdw.key';
                ALTER SYSTEM SET ssl=on;
                SELECT pg_reload_conf();""")
    deadline = time.monotonic() + 5
    while sql("pg", "SHOW ssl;") != "on":
        assert time.monotonic() < deadline, "SSL reload failed"
        time.sleep(0.1)
    password = secrets.token_hex(16)
    sql("pg", f"""
        CREATE ROLE report_reader LOGIN PASSWORD '{password}';
        CREATE SCHEMA reporting;
        CREATE TABLE reporting.product_snapshot(product_id int PRIMARY KEY,label text NOT NULL);
        INSERT INTO reporting.product_snapshot VALUES (42,'remote'),(43,'other');
        GRANT USAGE ON SCHEMA reporting TO report_reader;
        GRANT SELECT ON reporting.product_snapshot TO report_reader;
    """)
    variables = (
        "\\set fdw_host localhost\n\\set fdw_port 5432\n\\set fdw_dbname example_check\n"
        f"\\set fdw_ca /tmp/fdw.crt\n\\set fdw_password {password}\n"
    )
    path = "skills/postgres-guideline/fdw.md"
    sql("pg", variables + block(path, "CREATE SERVER reporting_server"))
    plan = sql("pg", block(path, "EXPLAIN (VERBOSE, COSTS ON)"))
    assert "Remote SQL:" in plan and "product_id = 42" in plan, plan
    assert sql("pg", """
        SET ROLE integration_reader;
        SELECT product_id,label FROM integration.product_snapshot WHERE product_id=42;
        RESET ROLE;
        SELECT bool_and(s.ssl) FROM pg_stat_ssl s JOIN pg_stat_activity a USING(pid)
        WHERE a.usename='report_reader';
    """) == "42|remote\nt"
    sql("pg", """SET ROLE integration_reader;
                INSERT INTO integration.product_snapshot VALUES (99,'blocked');""",
        error="permission denied for table product_snapshot")
    print("postgres_fdw: verify-full TLS, mapping, pushdown and remote read-only grants verified", flush=True)


def pg_spatial_and_vector(config):
    import psycopg
    path = "skills/postgres-guideline/postgis.md"
    print(sql("pg", block(path, "CREATE EXTENSION IF NOT EXISTS postgis")), flush=True)
    sql("pg", block(path, "CREATE TABLE app.place"))
    sql("pg", """INSERT INTO app.place(label,location) VALUES
        ('near',ST_SetSRID(ST_MakePoint(126.9790,37.5665),4326)::geography),
        ('far',ST_SetSRID(ST_MakePoint(129.0756,35.1796),4326)::geography); ANALYZE app.place;""")
    query = block(path, "ST_DWithin(location").replace("EXPLAIN (ANALYZE, BUFFERS)", "")
    rows = sql("pg", query).splitlines()
    assert [row.split("|")[1] for row in rows] == ["서울시청", "near"], rows
    # 작은 fixture에서 강제 계획은 인덱스 적격성만 증명하며 성능 수치로 쓰지 않는다.
    plan = sql("pg", "SET enable_seqscan=off; EXPLAIN (ANALYZE, BUFFERS) " + query)
    assert "idx_place_location" in plan, plan
    sql("pg", """INSERT INTO app.place(label,location)
                VALUES ('wrong-srid',ST_SetSRID(ST_MakePoint(0,0),3857));""", error="Only lon/lat")
    path = "skills/postgres-guideline/pgvector.md"
    print("pgvector " + sql("pg", block(path, "CREATE EXTENSION IF NOT EXISTS vector")), flush=True)
    sql("pg", block(path, "CREATE TABLE app.document_chunk"))
    sql("pg", """INSERT INTO app.document_chunk(tenant_id,content,embedding)
                SELECT CASE WHEN i%2=0 THEN 7 ELSE 8 END, 'chunk '||i,
                       ARRAY[1.0, i/1000.0, i/2000.0]::vector
                FROM generate_series(1,5000) i;""")
    sql("pg", "INSERT INTO app.document_chunk(tenant_id,content,embedding) VALUES (7,'zero','[0,0,0]');", error="chk_document_chunk_nonzero")
    sql("pg", "INSERT INTO app.document_chunk(tenant_id,content,embedding) VALUES (7,'dimension','[1,0]');", error="expected 3 dimensions")
    exact_query = block(path, "CREATE TABLE app.document_chunk").split("-- ANN 인덱스가 없으면", 1)[1]
    exact_query = exact_query[exact_query.index("SELECT document_chunk_id"):]
    exact = sql("pg", exact_query).splitlines()
    sql("pg", block(path, "CREATE INDEX idx_document_chunk_embedding"))
    sql("pg", "ANALYZE app.document_chunk;")
    iterative = block(path, "SET LOCAL hnsw.iterative_scan")
    approximate = sql("pg", iterative).splitlines()
    assert [row.split("|")[0] for row in exact] == [row.split("|")[0] for row in approximate]
    plan = sql("pg", "SET enable_seqscan=off; EXPLAIN (ANALYZE, BUFFERS) " + exact_query)
    assert "idx_document_chunk_embedding" in plan, plan
    # 실제 ANN 경로에서도 tenant RLS와 트랜잭션 종료 후 설정 복원을 검사한다.
    sql("pg", """
        ALTER TABLE app.document_chunk ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_chunk ON app.document_chunk
          USING (tenant_id=(SELECT NULLIF(current_setting('app.tenant_id',true),'')::bigint));
        GRANT USAGE ON SCHEMA public TO app_runtime;
        GRANT SELECT ON app.document_chunk TO app_runtime;
    """)
    with psycopg.connect(**config, autocommit=True) as conn:
        conn.execute("SET ROLE app_runtime")
        with conn.transaction():
            conn.execute("SELECT set_config('app.tenant_id','7',true)")
            conn.execute("SET LOCAL enable_seqscan=off")
            conn.execute("SET LOCAL hnsw.iterative_scan=strict_order")
            conn.execute("SET LOCAL hnsw.ef_search=100")
            # WHERE를 빼도 RLS 자체가 테넌트를 격리해야 한다.
            result = conn.execute(exact_query.replace("WHERE tenant_id = 7\n", "")).fetchall()
            assert [str(row[0]) for row in result] == [row.split("|")[0] for row in exact]
            assert all(int(row[0]) % 2 == 0 for row in result)
        assert conn.execute("SELECT count(*) FROM app.document_chunk").fetchone() == (0,)
        assert conn.execute("SHOW hnsw.iterative_scan").fetchone() == ("off",)
    print("PostGIS: meter radius + GiST; pgvector: exact/HNSW, dimensions, filtered recall and RLS verified", flush=True)


def mysql_84():
    assert sql("mysql", "SELECT @@innodb_adaptive_hash_index,@@innodb_change_buffering,@@restrict_fk_on_non_standard_key;") == "0\tnone\t1"
    sql("mysql", block("skills/mysql-guideline/operations.md", "SELECT @@version,"))
    assert sql("mysql", "SHOW VARIABLES LIKE 'default_authentication_plugin';") == ""
    sql("mysql", "CREATE USER 'auth_probe'@'localhost' IDENTIFIED BY 'disposable-test-only';")
    assert sql("mysql", "SELECT plugin FROM mysql.user WHERE user='auth_probe';") == "caching_sha2_password"
    sql("mysql", "ALTER USER 'auth_probe'@'localhost' IDENTIFIED WITH mysql_native_password BY 'disposable-test-only';",
        error="Plugin 'mysql_native_password' is not loaded")
    sql("mysql", "DROP USER 'auth_probe'@'localhost';")
    sql("mysql", "SHOW REPLICA STATUS;")
    sql("mysql", "SHOW SLAVE STATUS;", error="syntax")
    sql("mysql", "CREATE TABLE nonunique_parent(code int,KEY idx_parent_code(code));")
    child = "CREATE TABLE fk_probe(code int,FOREIGN KEY(code) REFERENCES nonunique_parent(code));"
    sql("mysql", child, error="Missing unique key")
    sql("mysql", "ALTER TABLE nonunique_parent ADD UNIQUE KEY uq_parent_code(code);")
    sql("mysql", child)
    sql("mysql", "INSERT INTO fk_probe VALUES(1);", error="foreign key constraint fails")
    sql("mysql", "ALTER TABLE fk_probe ADD COLUMN label varchar(30), ALGORITHM=INSTANT;")
    sql("mysql", "DROP TABLE fk_probe; DROP TABLE nonunique_parent;")


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-major", type=int, choices=[16, 18], default=18)
    parser.add_argument("--extensions", action="store_true", help="Run PostGIS/pgvector examples using the test image")
    options = parser.parse_args()
    import django  # Fail before starting containers if test dependencies are missing.
    import psycopg
    assert shutil.which("openssl"), "OpenSSL is required for the FDW TLS check"
    for check in [metadata, sqlite_and_sync]:
        check()
        print(f"PASS {check.__name__}", flush=True)
    with databases(options.pg_major, options.extensions) as config:
        for check, args in [
            (pg_cutover, ()), (pg_backfill, (config,)), (showcase, ()),
            (partitions_and_subtypes, ()), (parent_locks, (config,)),
            (pg_version_and_rls, (config,)), (pg_builtin_extensions, ()), (pg_fdw, ()),
            (mysql_examples, ()), (mysql_84, ()), (django_backfill, (config,)),
        ]:
            check(*args)
            print(f"PASS {check.__name__}", flush=True)
        if options.extensions:
            pg_spatial_and_vector(config)
            print("PASS pg_spatial_and_vector", flush=True)
        else:
            print("SKIP PostGIS/pgvector: build scripts/Dockerfile.postgres, then pass --extensions", flush=True)
