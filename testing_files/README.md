# Testing files

Drop sample documents here for local and pytest checks.

Supported: `.pdf`, `.docx`, `.doc`, `.csv`, `.txt`, `.xlsx`

```bash
python run_local_extract.py
pytest test_api.py -k local_fixtures -s
```
