# Release dependency constraints

Use the pinned/compatible release set when preparing a packaged release:

```bat
python -m pip install -r requirements.txt -c constraints-release.txt
```

`constraints-release.txt` records a set known to work with this project, including the versions observed on the Windows 1.2.8
verification environment. It does not change `build.bat`; use the constraint file in an explicit build environment only.
