# Third-party dependencies and licences

Direct dependencies (see `requirements.txt`) and their licences. All are
permissive, widely-used open-source packages; none impose attribution payments
or copyleft distribution requirements incompatible with building a product.

| Package | Licence | Used for |
|---|---|---|
| Flask | BSD-3-Clause | Web framework |
| Flask-SQLAlchemy | BSD-3-Clause | ORM integration |
| Flask-Login | MIT | Session auth |
| SQLAlchemy | MIT | ORM/database toolkit |
| pandas | BSD-3-Clause | Dataset processing |
| NumPy | BSD-3-Clause | Numeric computation |
| openpyxl | MIT | Excel (xlsx/xls) reading/writing |
| scikit-learn | BSD-3-Clause | ML utilities (available for future features) |
| matplotlib | PSF (BSD-like) | Report chart rendering (Agg backend) |
| python-dotenv | BSD-3-Clause | .env loading |
| pytest | MIT | Testing |
| Bootstrap (CDN in templates) | MIT | UI CSS framework |
| Chart.js (CDN in templates) | MIT | Browser-side charting |

Frontend assets are loaded from CDNs (jsdelivr); for offline/air-gapped
deployments vendor the files into `static/` and update `templates/base.html`.

No proprietary or restricted code is incorporated. All project source is
original work developed with AI assistance as documented in `DEVELOPMENT.md`.
