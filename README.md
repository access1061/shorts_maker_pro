# Shorts Maker Pro

Windows에서 모니터 화면을 녹화하고 9:16 세로 쇼츠 영상으로 변환하는 프로그램입니다. Windows 11 스타일의 Sun Valley(sv-ttk) 다크 테마를 사용합니다.

## 실행 파일

[Releases](https://github.com/access1061/shorts_maker_pro/releases/latest)에서 `ShortMakerPro-Windows.zip`을 받아 압축을 풀고 `ShortMaker.exe`를 실행합니다. 실행 파일과 함께 `ffmpeg.exe`, `_internal` 폴더가 필요합니다. Python 설치는 필요하지 않습니다. 영상은 사용자 폴더의 `ShortMaker/output`에 저장됩니다.

## 소스 코드 실행

Windows 10/11, Python 3.9 이상(Tkinter 포함)이 필요합니다. `ffmpeg.exe`는 용량 문제로 저장소에 포함하지 않으므로 [gyan.dev FFmpeg 빌드](https://www.gyan.dev/ffmpeg/builds/)에서 받아 `bin/ffmpeg.exe`를 `app.py`와 같은 폴더에 두고 실행하세요.

```powershell
pip install pyaudiowpatch sv-ttk
python app.py
```

1. 모니터를 선택하고, 필요한 경우 자유 비율 또는 9:16 고정으로 영역을 드래그하고 마우스를 놓아 확정합니다. Esc는 취소, `전체 화면`은 영역 선택 해제입니다. `녹화 범위 확인`을 누르면 실제 녹화 범위만 밝게 표시되며, `확인(Enter)`/`취소(Esc)` 결과가 화면 카드 아래에 `✔ 확인됨`(초록) 또는 `● 미확인`(주황)으로 남습니다. 녹음 장치는 기본으로 `PC 소리 · (기본 출력 장치)`가 선택됩니다. 소리가 필요 없다면 `녹음 안 함`을 선택합니다.
2. 커서 따라가기 또는 블러 배경을 선택합니다.
3. **녹화 시작** 버튼 또는 F8을 누르고, 마칠 때 다시 누릅니다. 녹화 중에는 선택 화면 위쪽에 녹화 상태가 표시되며 이 표시는 영상에도 포함될 수 있습니다.
4. 변환이 끝나면 저장 폴더에서 원본 MKV와 세로 MP4를 확인합니다. 소스 실행 시에는 프로젝트의 `output` 폴더입니다.

커서는 녹화 영상에 포함됩니다. 커서가 선택한 모니터 밖으로 나가면 크롭 위치는 마지막 위치에 머뭅니다. 오디오는 장치 하나를 선택합니다. `PC 소리 · 장치명`은 그 출력 장치(스피커, 헤드폰, 블루투스 헤드폰 등)로 나가는 소리를 WASAPI 루프백으로 녹음하며, 스테레오 믹스 같은 별도 설정이 필요 없습니다. 소리가 다른 출력 장치로 나가면 그 장치를 선택하세요. 녹화가 끝나면 화면 시작 시각에 맞춰 소리를 원본 MKV에 합칩니다. 배타 모드로 소리를 내는 프로그램의 소리는 녹음되지 않습니다. 그 밖의 항목은 마이크 등 DirectShow 녹음 장치이며, 마이크와 PC 소리를 동시에 녹음하지는 않습니다.

녹화 중 앱을 닫을 수 없습니다. 오류가 발생하면 `output` 폴더의 오류 로그를 확인하세요. 변환에 실패해도 원본은 삭제하지 않습니다. F8이 다른 프로그램과 충돌하면 버튼을 사용하세요.

## 배포판 빌드

```powershell
pip install pyinstaller pyaudiowpatch sv-ttk
python build.py
```

`build.py`는 실행할 때마다 `app.py`의 `VERSION` 마지막 자리를 1 올리고(예: 1.0.1 → 1.0.2), PyInstaller로 빌드한 뒤 `ffmpeg.exe`와 `배포_안내.txt`를 넣어 `dist/ShortMakerPro-Windows.zip`으로 압축합니다. 버전은 창 제목, 앱 머리글, exe 파일 속성에 표시됩니다. 버전을 그대로 두고 다시 빌드하려면 `python build.py --no-bump`를 사용합니다.

## 테스트

```powershell
python -m unittest -v
```

## 라이선스 고지

배포판에는 gyan.dev의 FFmpeg 8.0.1 full build가 포함되며, 이 빌드는 GPL 버전 3 이상으로 제공됩니다. 자세한 내용은 https://www.gyan.dev/ffmpeg/builds/ 와 https://ffmpeg.org/legal.html 을 참고하세요. UI 테마는 [Sun Valley ttk theme](https://github.com/rdbende/Sun-Valley-ttk-theme)(MIT)를 사용합니다.
