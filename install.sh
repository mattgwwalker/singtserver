#! /bin/bash
echo "Hi!"
echo 
echo "This will install Singt on your computer's desktop."
echo "Once we're finished with the test, you may delete"
echo "it just by dragging the 'Singt' folder from your"
echo "desktop to the Trash."
echo
echo "This installation will also install optional"
echo "components of macOS: specifically, python3, and pipenv."
echo
read -p "Type enter to continue or Ctrl+C to stop: " input
echo

PYTHON3_VERSION=$(python3 --version)

echo "python3 version:" $PYTHON3_VERSION

# Install pipenv
pip3 install pipenv --user

PIPENV=$(pipenv --version)
echo "pipenv version:" $PIPENV


# Create base directory on the Desktop
cd ~/Desktop
mkdir Singt
cd Singt


# Download 'Singt'
git clone https://github.com/mattgwwalker/singt.git


# Download my version of PyOgg
git clone --branch libraries https://github.com/mattgwwalker/PyOgg.git


# Create the virtual environment
cd singt
pipenv install
pipenv shell

echo testing
