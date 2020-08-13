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


    def get_combination(self, track_id=None, take_ids=[]):
        # Sanity check arguments
        if (track_id is None
            and len(take_ids) == 0):
            raise Exception(
                "Getting a combination from the database requires "+
                "at least a Track ID or at least one Take ID"
            )

        # Get combination from database.
        # See answers to https://stackoverflow.com/questions/63356820/sql-select-from-many-to-one
        # and https://stackoverflow.com/a/5766293/562930
        def get_combo(cursor):
            # Turn on foreign key constraints
            cursor.execute("PRAGMA foreign_keys = ON;")
            
            print("track_id:", track_id)
            print("take_ids:", take_ids)

            if track_id is None:
                assert len(take_ids) > 0
                sql = (
                    "SELECT id\n"+
                    "FROM Combinations\n"+
                    "WHERE backingTrackId IS NULL\n"+
                    "      AND id IN\n"+
                    "      (SELECT combinationId\n"+
                    "       FROM CombinationsDetail\n"+
                    "       GROUP BY combinationId\n" +
                    "       HAVING SUM(CASE WHEN takeId IN ({seq}) THEN 1 ELSE 0) = ?".format(
                        seq=",".join(["?"]*len(take_ids))
                    )
                )
                print("sql:",sql)
                cursor.execute(
                    sql,
                    (*take_ids, len(take_ids))
                )
                       
            elif len(take_ids) == 0:
                sql = (
                    "SELECT id\n"+
                    "FROM Combinations\n"+
                    "WHERE backingTrackId = ?\n"+
                    "      AND NOT EXISTS\n"+
                    "      (SELECT * \n"+
                    "       FROM CombinationsDetail\n"+
                    "       WHERE combinationId = Combinations.id)"
                )
                print("sql:",sql)
                cursor.execute(
                    sql,
                    (track_id, )
                )
                       
            else:
                sql = ("SELECT id\n"+
                       "FROM Combinations\n"+
                       "WHERE backingTrackId = ?\n"+
                       "      AND id IN\n"+
                       "      (SELECT combinationId\n"+
                       "       FROM CombinationsDetail\n"+
                       #"       WHERE combinationId = Combinations.id\n"+
                       "       GROUP BY combinationId\n" +
                       "       HAVING SUM(CASE WHEN takeId IN ({seq}) THEN 1 ELSE 0 END) = ?)").format(
                           seq=",".join(['?']*len(take_ids))
                       )
                print("sql:",sql)
                cursor.execute(
                    sql,
                    (track_id, *take_ids, len(take_ids))
                )

            # Although there should be at most only one combo id that
            # matches the track and takes specification, even if there
            # are more than one, we'll just return the first (or None
            # if there aren't any).
            row = cursor.fetchone()
            print("row:", row)
            if row is None:
                return None
            combo_id = row[0]
            return combo_id
                
        d = self.dbpool.runInteraction(get_combo)

        def on_success(data):
            log.info("Successfully added combination to database; combination id: "+str(data))
            return data
        def on_error(error):
            log.error("Failed to add combination to the database: "+str(error))
            raise Exception("Failed to add combination to the database")

        d.addCallback(on_success)
        d.addErrback(on_error)

        return d


    def add_combination(self, track_id=None, take_ids=[]):
        # Sanity check arguments
        if (track_id is None
            and len(take_ids) == 0):
            raise Exception(
                "Adding a combination to the database requires "+
                "at least a Track ID or at least one Take ID"
            )

        # Create combination in database
        def _add_combo(cursor):
            # Turn on foreign key constraints
            cursor.execute("PRAGMA foreign_keys = ON;")
            
            print("track_id:", track_id)
            cursor.execute(
                "INSERT INTO Combinations (backingTrackId) VALUES (?)",
                (track_id,)
            )
            combo_id = cursor.lastrowid

            for take_id in take_ids:
                cursor.execute(
                    "INSERT INTO CombinationsDetail (combinationId, takeId) "+
                    "VALUES (?,?)",
                    (combo_id, take_id)
                )
                
            return combo_id
                
        d = self.dbpool.runInteraction(_add_combo)

        def on_success(data):
            log.info("Successfully added combination to database; combination id: "+str(data))
            return data
        def on_error(error):
            log.error("Failed to add combination to the database: "+str(error))
            raise Exception("Failed to add combination to the database")

        d.addCallback(on_success)
        d.addErrback(on_error)

        return d
        
