# YouTube·Instagram 미디어 추출기

YouTube 영상/Shorts 또는 Instagram 릴스/게시물 링크를 넣으면 영상과 소리를 원하는 조합으로 빠르게 저장하는 Windows 데스크톱 앱입니다. 여러 링크를 큐에 넣고 순서대로 처리할 수 있습니다.

**developed by yeohj0710**

## 사용 방법

1. `run_app.ps1`로 개발 버전을 실행합니다.
2. YouTube 영상/Shorts 또는 Instagram 릴스 링크를 붙여넣습니다. 여러 개는 줄마다 하나씩 넣어도 됩니다.
3. `영상`과 `소리`를 체크합니다. 둘 다 켜면 소리 포함 MP4, 소리만 켜면 MP3, 영상만 켜면 무음 MP4로 저장됩니다.
4. 영상 화질과 소리 품질을 선택합니다.
5. 저장 폴더를 확인하거나 `변경`으로 바꿉니다. `열기`로 바로 폴더를 열 수도 있습니다.
6. `큐에 추가하고 추출 시작`을 누릅니다.
7. 처리 중에도 링크를 더 넣으면 뒤에 대기열로 붙고, 앞 작업부터 자동 처리됩니다.
8. 완료되면 `최근 저장 폴더 열기`로 결과를 확인합니다.

## 기본 폴더

```text
youtube-instagram-media-extractor/
  YouTube·Instagram 미디어 추출기.exe
  다운로드한 미디어/
  사용설명서.html
  프로그램 구성 파일/
    개발 파일/
      src/youtube_instagram_media_extractor/
      assets/
```

빌드 후에는 기존 `media-summary-note-generator`와 비슷하게 repo 루트에 사용자용 파일만 놓이고, 실행에 필요한 파일과 개발 파일은 `프로그램 구성 파일` 폴더에 정리됩니다.

```text
youtube-instagram-media-extractor/
  YouTube·Instagram 미디어 추출기.exe
  다운로드한 미디어/
  사용설명서.html
  프로그램 구성 파일/
```

영상이 포함된 작업은 `다운로드한 미디어` 안에 영상 제목 폴더가 만들어지고, 그 안에 MP4 파일과 1초 간격 스크린샷 JPG가 함께 저장됩니다. 소리만 저장하면 MP3 파일만 저장됩니다.

## 개발 실행

```powershell
.\run_app.ps1
```

## 테스트

```powershell
python -m pytest
```

## 배포 빌드

```powershell
.\build.ps1
```

OpenAI API 키는 필요 없습니다. 내부 다운로드/변환은 `yt-dlp`와 `FFmpeg`를 사용합니다.
