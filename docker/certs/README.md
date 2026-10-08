# 추가 신뢰 CA

백신(예: Norton 의 SSL/TLS 검사)이나 사내 프록시가 HTTPS 를 가로채는 PC 에서는 컨테이너 안의
pip, npm, `ollama pull`, Hugging Face 다운로드가 인증서 오류로 실패한다.
그 루트 인증서를 PEM 형식 `*.crt` 로 이 폴더에 두면 이미지 빌드와 Ollama 컨테이너가 신뢰한다.
`*.crt` 는 PC 마다 다르므로 git 에 올리지 않는다.

Windows 에서 내보내기 (PowerShell, `<이름>` 은 인증서 주체의 일부):

```powershell
$c = Get-ChildItem Cert:\LocalMachine\Root | Where-Object Subject -like "*<이름>*" | Select-Object -First 1
$pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks').Replace("`r`n","`n") + "`n-----END CERTIFICATE-----`n"
[IO.File]::WriteAllText("$PWD\docker\certs\proxy-root.crt", $pem)
```
