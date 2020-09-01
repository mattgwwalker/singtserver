from setuptools import setup

setup(name='singtserver',
      version='0.7',
      packages=["singtserver"],
      include_package_data=True,
      install_requires=[
          "art",
          "numpy",
          "singtcommon",
          "twisted",
      ]
)
