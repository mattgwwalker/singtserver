import cProfile

from server import start

cProfile.run('start()', "profile.data")
