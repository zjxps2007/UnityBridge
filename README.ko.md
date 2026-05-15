# UnityBridge

한국어 | [English](README.md)

UnityBridge는 로컬 HTTP connector를 통해 Unity Editor를 제어하는 standalone CLI,
Python-native 클라이언트, Unity 패키지입니다.

CLI는 `~/.unity-bridge/instances/*.json` heartbeat 파일로 실행 중인 Unity Editor를
발견하고, 대상 Editor를 선택한 뒤 `http://127.0.0.1:{port}/command`로 JSON 명령을
보냅니다.

## 빠른 시작

### 1. Unity 패키지 설치

Unity Editor에서 `Window > Package Manager > + > Add package from git URL...`을 열고
아래 URL을 붙여넣습니다.

```text
https://github.com/zjxps2007/UnityBridge.git?path=unity-bridge-connector
```

### 2. CLI 설치

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.ps1 | iex
```

macOS/Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/zjxps2007/UnityBridge/main/install.sh | sh
```

### 3. 연결 확인

Unity 프로젝트를 열어둔 상태에서 실행합니다.

```powershell
unity-bridge status
unity-bridge tools
```

## 문서

- [INSTALL.ko.md](INSTALL.ko.md): standalone 설치, 버전 고정, 업데이트, release asset.
- [COMMANDS.ko.md](COMMANDS.ko.md): CLI 명령어, 공통 옵션, custom tool 호출.
- [PYTHON_PACKAGE.ko.md](PYTHON_PACKAGE.ko.md): 개발 및 Agent 통합용 Python 패키지 모드.

## 라이선스

UnityBridge는 MIT License로 배포됩니다.

제3자 라이선스 고지는 [NOTICE.md](NOTICE.md)를 확인하세요.
