from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.config import settings
from services.api.app.database import migrate
from services.api.app import services
from services.api.app.indexer import index_project

migrate()
source = Path('examples/synthetic-project').resolve()
root = (settings.workspace_root / 'synthetic-project').resolve()
if root.exists():
    shutil.rmtree(root)
shutil.copytree(source, root)
existing = next((p for p in services.list_projects() if Path(p['path']) == root), None)
project = existing or services.create_project('Synthetic demo', str(root))
print(index_project(project['id'], root))
print(f"Seeded project {project['id']}: {project['name']} at {root}")
