#!/bin/bash
# OpenBB Platform Helper Script

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}OpenBB Platform Helper${NC}"
echo "====================="
echo ""

case "$1" in
    "activate")
        echo -e "${GREEN}Activating virtual environment...${NC}"
        source venv/bin/activate
        echo "Virtual environment activated!"
        exec bash
        ;;
    "test")
        echo -e "${GREEN}Running test script...${NC}"
        source venv/bin/activate
        python test_openbb.py
        ;;
    "api")
        echo -e "${GREEN}Starting API server...${NC}"
        source venv/bin/activate
        cd openbb_platform
        uvicorn openbb_core.api.rest_api:app --host 0.0.0.0 --port 8000 --reload
        ;;
    "build")
        echo -e "${GREEN}Rebuilding OpenBB Platform...${NC}"
        source venv/bin/activate
        python -c "import openbb; openbb.build()"
        ;;
    "install")
        echo -e "${GREEN}Running development installation...${NC}"
        source venv/bin/activate
        cd openbb_platform
        python dev_install.py -e
        ;;
    "pytest")
        echo -e "${GREEN}Running pytest...${NC}"
        source venv/bin/activate
        pytest openbb_platform -m "not integration"
        ;;
    "shell")
        echo -e "${GREEN}Starting Python shell with OpenBB...${NC}"
        source venv/bin/activate
        python -c "from openbb import obb; import code; code.interact(local=locals(), banner='OpenBB Platform Shell\n>>> from openbb import obb\n')"
        ;;
    *)
        echo "Usage: ./openbb.sh [command]"
        echo ""
        echo "Commands:"
        echo "  activate  - Activate virtual environment"
        echo "  test      - Run test script"
        echo "  api       - Start REST API server"
        echo "  build     - Rebuild OpenBB Platform"
        echo "  install   - Run development installation"
        echo "  pytest    - Run unit tests"
        echo "  shell     - Start Python interactive shell"
        echo ""
        echo "Example: ./openbb.sh test"
        ;;
esac
