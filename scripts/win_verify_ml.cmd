@echo off
setlocal
cd /d %~dp0..

call .venv\Scripts\activate

REM Register a tiny toy model for sanity
powershell -NoProfile -Command ^
  "$code = @'
from services.ml.registry import register_model
from sklearn.linear_model import LogisticRegression
import numpy as np
X = np.random.randn(40,4); y = (np.random.rand(40)>0.5).astype(int)
mdl = LogisticRegression().fit(X,y)
import numpy as _np
setattr(mdl, \"feature_names_in_\", _np.array(list(\"abcd\")))
register_model(\"toy_api\", mdl, alias=\"production\")
print(\"registered toy_api -> production\")
'@; $tmp = 'runtime\_reg_toy.py'; New-Item -ItemType Directory -Force -Path 'runtime' > $null; Set-Content -Path $tmp -Value $code; .venv\Scripts\python.exe $tmp"

REM Start API and probe endpoints
powershell -NoProfile -Command ^
  "$p = Start-Process -FilePath '.venv\Scripts\python.exe' -ArgumentList '-m uvicorn backend.api:app --host 127.0.0.1 --port 8000' -PassThru; ^
   Start-Sleep -Seconds 3; ^
   Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing | Out-Host; ^
   Invoke-WebRequest -Uri 'http://127.0.0.1:8000/ml/status' -UseBasicParsing | Out-Host; ^
   $body = @{ model_name='toy_api'; alias='production'; items=@(@{symbol='AAPL'; features=@{a=0.1;b=0.2;c=0.3;d=0.4}}) } | ConvertTo-Json; ^
   Invoke-WebRequest -Uri 'http://127.0.0.1:8000/ml/predict' -Method POST -ContentType 'application/json' -Body $body -UseBasicParsing | Out-Host; ^
   Stop-Process -Id $p.Id -Force"

echo Done.
endlocal
