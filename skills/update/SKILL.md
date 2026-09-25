---
name: update
description: Update the installed easy-rdbms plugin itself in Claude Code or Codex, refresh its marketplace, reinstall the current plugin version, and verify the result. Use for easy-rdbms update, plugin update, 플러그인 업데이트, 플러그인 갱신. This is plugin maintenance, not a database engine upgrade, extension update, or schema migration.
---

# Easy RDBMS 업데이트

사용자가 이 플러그인의 업데이트를 요청했을 때만 실행한다. 현재 대화의 실행 환경에 맞는
절차 하나를 사용한다. 두 CLI가 설치되어 있다는 이유로 둘 다 갱신하지 않는다.
사용자가 두 환경을 요청했다면 각각 실행한다.

## Codex

1. `codex plugin list --marketplace easy-rdbms --json`으로
   `easy-rdbms@easy-rdbms`의 설치 여부·버전·마켓플레이스 출처를 확인한다.
2. Git 마켓플레이스에서 설치했다면 아래 명령을 순서대로 실행한다. 앞 단계가 실패하면
   다음 단계를 실행하지 않는다. `marketplace upgrade`는 목록 갱신이므로 `plugin add`까지
   실행해야 설치된 플러그인도 갱신된다.

   ```bash
   codex plugin marketplace upgrade easy-rdbms && \
     codex plugin add easy-rdbms@easy-rdbms --json && \
     codex plugin list --marketplace easy-rdbms --json
   ```

3. 설치 결과와 마지막 목록의 플러그인 ID·버전을 대조한다. 다운로드 완료와 현재 대화에
   로드된 버전을 구분하고, 새 대화에서 `$easy-rdbms:update` 등 갱신된 스킬을 사용하도록 안내한다.

## Claude Code

1. `claude plugin list --json`과 `claude plugin marketplace list --json`에서 대상 플러그인의
   설치 버전·scope·마켓플레이스 출처를 확인한다.
2. 아래 명령을 순서대로 실행하고 실패 시 멈춘다. 여러 scope에 설치되어 있으면 사용자가
   지정한 scope 또는 현재 프로젝트에 적용되는 scope를 `plugin update --scope`로 명시한다.

   ```bash
   claude plugin marketplace update easy-rdbms && \
     claude plugin update easy-rdbms@easy-rdbms && \
     claude plugin list --json
   ```

3. 대상 scope의 설치 버전을 마켓플레이스 `installLocation`의 `.claude-plugin/plugin.json`
   `version`과 대조한다. 다르면 갱신이 적용되지 않은 것이므로 성공으로 보고하지 않는다.
   현재 세션에서는 `/reload-plugins`를 실행하거나
   새 세션을 시작해야 갱신된 플러그인이 적용된다고 안내한다.

## 예외와 완료 보고

- 설치되지 않았으면 이를 알리고 README의 설치 절차를 안내한다. 다른 플러그인을 설치하거나
  삭제하지 않는다.
- 로컬 경로 또는 고정된 태그에서 설치했다면 그 출처를 먼저 알린다. 개발 중인 파일·버전·고정
  설정을 임의로 바꾸거나 최신 원격 브랜치로 교체하지 않는다. Git 갱신은 설정된 ref를 따른다.
- CLI가 없거나 해당 하위 명령이 지원되지 않으면 실제 오류를 보고한다. CLI 자체를 임의로
  설치하거나 존재하지 않는 `codex plugin update` 명령을 만들지 않는다.
- 성공했을 때만 **환경, 이전 → 설치 버전, 적용에 필요한 새 세션/다시 로드**를 짧게 보고한다.
  버전이 그대로면 해당 마켓플레이스에서 변경된 버전이 없다고 명시한다.
- 사용자 설정·마켓플레이스 JSON·플러그인 캐시는 직접 편집하지 않는다. 세션 시작 훅에서
  네트워크 업데이트를 실행하거나 플러그인의 자동 업데이트 설정을 몰래 바꾸지 않는다.

공식 근거:
[Codex 플러그인](https://developers.openai.com/codex/plugins/) ·
[Codex 마켓플레이스](https://developers.openai.com/codex/plugins/build/) ·
[Claude Code 업데이트](https://code.claude.com/docs/en/plugins/install#keep-plugins-updated).
실행할 CLI의 `plugin --help`와 하위 명령 `--help`도 확인할 수 있다.
