from twisted.enterprise import adbapi
from twisted.logger import Logger

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("database")

class Database:
    def __init__(self, db_filename):

        # Note if database already exists
        database_exists = db_filename.is_file()

        # Open a connection to the database.  SQLite will create the file if
        # it doesn't already exist.
        self.dbpool = adbapi.ConnectionPool("sqlite3", db_filename)

        # If the database did not exist, initialise the database
        if not database_exists:
            print("Database requires initialisation")
            self._d = self.dbpool.runInteraction(self._initialise_database)
            def on_success(data):
                log.info("Database successfully initialised")
            def on_error(data):
                log.error("Failed to initialise the database: "+str(data))
                reactor.stop()

            self._d.addCallback(on_success)
            self._d.addErrback(on_error)
        
    # Initialise the database structure from instructions in file
    def _initialise_database(self, cursor):
        log.info("Initialising database")
        initialisation_commands_filename = "database.sql"
        f = open(initialisation_commands_filename, "r")
        initialisation_commands = f.read()
        return cursor.executescript(initialisation_commands)


