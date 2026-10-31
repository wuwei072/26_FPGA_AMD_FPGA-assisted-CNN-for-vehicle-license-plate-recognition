# Dependency Notes

The reference model is deliberately implemented with the Python standard library so that it can run without NumPy or OpenCV.

The project has been verified with Python 3.14.7 from `C:\Users\Administrator\AppData\Local\Python\bin\python.exe`. The Windows Store `python` alias is not usable in the current sandbox, so use that full executable path if `python` fails. NumPy and OpenCV are not required by the reference model.

If a NumPy/OpenCV workflow is later required, install them manually in an approved Python environment:

```powershell
python -m pip install numpy opencv-python
```
