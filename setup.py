from setuptools import setup

setup(name='singtserver',
      version='0.6',
      packages=["singtserver"],
      include_package_data=True,
      install_requires=[
          "numpy",
          "singtcommon",
          "twisted",
      ]
)
