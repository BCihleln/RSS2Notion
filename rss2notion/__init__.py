# rss2notion 包

import os

try:
    from dotenv import load_dotenv
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, ".."))
    env_path = os.path.join(project_root, ".env")
    
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass
