from twisted.enterprise import adbapi
from twisted.logger import Logger

# Start a logger with a namespace for a particular subsystem of our application.
log = Logger("database")

class Database:
    def __init__(self, db_filename):

        # Note if database already exists
        database_exists = db_filename.is_file()

        # Callback for every connection that is established to the
        # database
        def setup_connection(connection):
            # Turn on foreign key constraints
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")

            # # Turn on column names in rows
            # import sqlite3
            # connection.row_factory = sqlite3.Row
        
        # Open a connection to the database.  SQLite will create the file if
        # it doesn't already exist.
        self.dbpool = adbapi.ConnectionPool(
            "sqlite3",
            db_filename,
            cp_openfun=setup_connection,
            check_same_thread=False # See https://twistedmatrix.com/trac/ticket/3629
        )

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
                       "       GROUP BY combinationId\n" +
                       "       HAVING SUM(CASE WHEN takeId IN ({seq}) THEN 1 ELSE 0 END) = ?)").format(
                           seq=",".join(['?']*len(take_ids))
                       )
                cursor.execute(
                    sql,
                    (track_id, *take_ids, len(take_ids))
                )

            # Although there should be at most only one combo id that
            # matches the track and takes specification, even if there
            # are more than one, we'll just return the first (or None
            # if there aren't any).
            row = cursor.fetchone()
            if row is None:
                return None
            combo_id = row[0]
            return combo_id
                
        d = self.dbpool.runInteraction(get_combo)

        def on_success(data):
            log.info("Successfully added combination to database; combination id: "+str(data))
            return data
        d.addCallback(on_success)
        
        def on_error(error):
            log.error("Failed to add combination to the database: "+str(error))
            raise Exception("Failed to add combination to the database")
        d.addErrback(on_error)

        return d


    def add_combination(self, track_id=None, take_ids=[]):
        """Adds combination into database.

        Returns combo_id.
        """
        log.info(f"Adding combination to database with track id = {track_id} and take_ids = {take_ids}")
        # Sanity check arguments
        if (track_id is None
            and len(take_ids) == 0):
            raise Exception(
                "Adding a combination to the database requires "+
                "at least a Track ID or at least one Take ID"
            )

        # Create combination in database
        def add_combo(cursor):
            # Create audio id
            cursor.execute("INSERT INTO AudioIdentifiers DEFAULT VALUES")
            audio_id = cursor.lastrowid
            
            print("track_id:", track_id)
            cursor.execute(
                "INSERT INTO Combinations (audioId, backingTrackId) VALUES (?, ?)",
                (audio_id, track_id)
            )
            combo_id = cursor.lastrowid

            for take_id in take_ids:
                cursor.execute(
                    "INSERT INTO CombinationsDetail (combinationId, takeId) "+
                    "VALUES (?,?)",
                    (combo_id, take_id)
                )
                
            return combo_id
                
        d = self.dbpool.runInteraction(add_combo)

        def on_success(data):
            log.info("Successfully added combination to database; combination id: "+str(data))
            return data
        def on_error(error):
            log.error("Failed to add combination to the database: "+str(error))
            raise Exception("Failed to add combination to the database")

        d.addCallback(on_success)
        d.addErrback(on_error)

        return d
        

    def get_track_audio_id(self, track_id):
        """Returns track's audio id or None."""
        def execute_sql(cursor):
            cursor.execute("SELECT audioId FROM BackingTracks WHERE id = ?",
                           (track_id,))
            results = cursor.fetchone()
            if results is None:
                return None
            else:
                return results[0]
            
        d = self.dbpool.runInteraction(execute_sql)
        def on_error(error):
            log.warn("Failed to get audio ID for track id ({track_id}): "+
                     str(error)
            )
            return error
        d.addErrback(on_error)

        return d
        

    def get_take_audio_id(self, take_id):
        """Returns take's audio id or None."""
        def execute_sql(cursor):
            cursor.execute("SELECT audioId FROM Takes WHERE id = ?",
                           (take_id,))
            results = cursor.fetchone()
            if results is None:
                return None
            else:
                return results[0]
            
        d = self.dbpool.runInteraction(execute_sql)
        def on_error(error):
            log.warn("Failed to get audio ID for take id ({take_id}): "+
                     str(error)
            )
            return error
        d.addErrback(on_error)

        return d

            
    def assign_participant(self, client_id, name):
        """Assigns the name to the client id."""

        def execute_sql(cursor):
            # First, check if the id already exists
            cursor.execute(
                "SELECT participantName FROM Participants WHERE id = ?",
                (client_id,)
            )
            row = cursor.fetchone()
            if row is None:
                # We don't currently have this ID, insert it
                cursor.execute(
                    "INSERT INTO Participants (id, participantName) "+
                    "VALUES (?, ?)",
                    (client_id, name)
                )
                return client_id

            # Otherwise, a row does already exist
            current_name = row[0]
            if name == current_name:
                # We have nothing to do, the database is already
                # correct
                return client_id

            # Otherwise, we need to update the database
            cursor.execute(
                "UPDATE Participants SET participantName = ? WHERE id = ?",
                (name, client_id)
            )
            return client_id
            

        d = self.dbpool.runInteraction(execute_sql)
        def on_error(error):
            log.warn(
                "Failed to add participant given name '{name}' and id '{client_id}': "+
                str(error)
            )
            return error
        d.addErrback(on_error)

        return d

    
    def get_participants(self):
        def execute_sql(cursor):
            cursor.execute("SELECT id, participantName FROM Participants")
            rows = cursor.fetchall()
            results = [{"id":id_, "name":name} for id_, name in rows]
            return results

        d = self.dbpool.runInteraction(execute_sql)
        def on_error(error):
            log.warn(
                "Failed to get participant list: "+
                str(error)
            )
            return error
        d.addErrback(on_error)

        return d
        
    def get_audio_ids_from_combination_id(self, combination_id):
        def execute_sql(cursor):
            # Get Track ID.  There should be either zero or one, but
            # not more.
            cursor.execute(
                "SELECT BackingTracks.audioId\n"+
                "FROM Combinations\n"+
                "LEFT JOIN BackingTracks\n"+
                "ON Combinations.backingTrackId = BackingTracks.id\n"+
                "WHERE combinations.id = ?",
                (combination_id,)
            )
            rows = cursor.fetchall()
            if len(rows) == 0:
                # We don't have a backing track; that's fine, move on
                # to the takes.
                backing_audio_ids = []
            elif len(rows) == 1:
                # We have one backing track
                row = rows[0]
                audio_id = row[0]
                backing_audio_ids = [audio_id]
            else:
                # We have more than one backing track; error.
                raise Exception(
                    f"More than one backing track matched "+
                    f"combination id {combination_id}; this "+
                    f"shouldn't be possible"
                )

            # Get the Take IDs.  There may be many of these.  But if
            # there wasn't a backing track id, then there needs to be
            # at least one Take ID.
            cursor.execute(
                "SELECT audioId\n"+
                "FROM CombinationsDetail\n"+
                "LEFT JOIN Takes\n"+
                "ON CombinationsDetail.id = Takes.combinationId\n"+
                "WHERE CombinationsDetail.combinationId = ?",
                (combination_id,)
            )
            rows = cursor.fetchall()
            if len(rows) == 0:
                # This is only as issue if we don't have any backing
                # tracks either
                if len(backing_audio_ids) == 0:
                    raise Exception(
                        f"We have neither a backing track nor takes "+
                        f"for the given combination id ({combination_id});"+
                        f"this shouldn't be possible"
                    )
            else:
                # Add the Take IDs to the list 
                takes_audio_ids = [row[0] for row in rows]
                backing_audio_ids += takes_audio_ids
                
            return backing_audio_ids

        d = self.dbpool.runInteraction(execute_sql)
        def on_error(error):
            log.warn(
                "Failed to get backing audio ids from combination id: "+
                str(error)
            )
            return error
        d.addErrback(on_error)

        return d
        
    def add_take(self, take_name, combination_id):
        def execute_sql(cursor):
            # Create audio id
            cursor.execute("INSERT INTO AudioIdentifiers DEFAULT VALUES")
            audio_id = cursor.lastrowid

            # Create take
            cursor.execute(
                "INSERT INTO Takes (audioId, combinationId, takeName, complete) "+
                "VALUES (?, ?, ?, 0)",
                (audio_id, combination_id, take_name)
            )
            take_id = cursor.lastrowid

            return take_id

        d = self.dbpool.runInteraction(execute_sql)
        def on_error(error):
            log.warn(
                "Failed to add take: "+
                str(error)
            )
            return error
        d.addErrback(on_error)

        return d
        
    def add_recording_audio_ids(self, take_id, participants):
        def execute_sql(cursor):
            audio_ids = []
            for participant_id in participants:
                # Create audio id
                cursor.execute("INSERT INTO AudioIdentifiers DEFAULT VALUES")
                audio_id = cursor.lastrowid

                # Add entry into Recordings
                cursor.execute(
                    "INSERT INTO Recordings "+
                    "(audioId, participantId, takeId, complete) "+
                    "VALUES (?, ?, ?, 0)",
                    (audio_id, participant_id, take_id)
                )
                
                audio_ids.append(audio_id)
            return audio_ids

        d = self.dbpool.runInteraction(execute_sql)
        def on_error(error):
            log.warn(
                "Failed to add recordings for participants: "+
                str(error)
            )
            return error
        d.addErrback(on_error)

        return d

