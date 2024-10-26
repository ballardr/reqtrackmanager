The database uses an ORM model to allow greatest ease of changing database backend.

# Development Environment
Development is being done in VSCode. Due to the prevelence of development tools on linux (and this author preferring linux development), the dev environment is intended to be used within a WSL environment when on Windows. Also, to remove relience on system installed python packages, we use a virtual environment, managed using poetry.

## Initial Setup
### WSL (Ubuntu 22.04)
sudo apt update && sudo apt upgrade
sudo apt install docker-compose-v2 docker.io
sudo apt install python3-pip python3-venv python3-poetry

poetry run code .


## Recommended VSCode Extensions
WSL
Python
Remote Development


