# Manga Print Generator

A phone-friendly web app to search image catalogues, download eligible images, remove duplicates, and export an A5 PDF with one image per page.

## Deploy from your phone

1. Extract this ZIP on your phone.
2. Upload the extracted project files and folders to the `BeingMirage/manga-print-generator` GitHub repository. Keep the `templates` folder and put `app.py`, `requirements.txt`, and `render.yaml` at the repository root.
3. Open https://render.com and sign in with GitHub.
4. Select **New +** → **Blueprint** and choose `BeingMirage/manga-print-generator`.
5. Click **Apply** to deploy using `render.yaml`.
6. Open the Render URL on your phone.

The free service can sleep when idle. Its temporary local storage may reset after restarts, so download your PDF before leaving the session.

## Sources and copyright

The app searches Openverse and Wikimedia Commons, which index media with reuse metadata. These catalogues may not contain actual pages from commercial manga series. The app does not scrape Pinterest, bypass paywalls, or download unauthorized manga scans. Check original source and licence terms before reuse.

## Local development

Python 3.10+: `pip install -r requirements.txt` then `python app.py`.
