/* Enable Foreign Keys.  This needs to be executed for each databse
connection as it feaults to disabled. */

PRAGMA foreign_keys = ON;

/* Create a Version table, giving the version number of this database
instance. Insert the version number */

CREATE TABLE Version (
       version INTEGER NOT NULL
);     
INSERT INTO Version (version) VALUES (2); /* This version */


/* Create the Participants table. */

CREATE TABLE Participants (
       id INTEGER PRIMARY KEY,
       participantName TEXT NOT NULL
);


/* Create the BackingTracks table. */

CREATE TABLE BackingTracks (
       id INTEGER PRIMARY KEY,
       trackName TEXT NOT NULL
);


/* Create the Combinations table.  A Combination is based on at most
one Backing Track and any number of Takes.  It describes the audio
heard by the participants when they record. */

CREATE TABLE Combinations (
       id INTEGER PRIMARY KEY,
       backingTrackId INTEGER REFERENCES BackingTracks(id)
);


/* Create the CombinationsDetail table, which allows the one-to-many
relationship of Combinations-to-Takes. */

CREATE TABLE CombinationsDetail (
       id INTEGER PRIMARY KEY,
       combinationId INTEGER REFERENCES Combinations(id),
       takeId INTEGER REFERENCES Takes(id)
);


/* Create the Takes table.  A Take is made up of many Recordings. A
take might not be complete. */

CREATE TABLE Takes (
       id INTEGER PRIMARY KEY,
       combinationId INTEGER NOT NULL REFERENCES Combinations(id),
       takeNumber INTEGER NOT NULL,
       takeName TEXT,
       complete BOOLEAN NOT NULL DEFAULT 0
);

/* Create the Recordings table.  Participants create recordings that
are associated with a given Take.  A recording might not be
complete. */

CREATE TABLE Recordings (
       id INTEGER PRIMARY KEY,
       participantId INTEGER NOT NULL REFERENCES Participants(id),
       takeId INTEGER NOT NULL REFERENCES Takes(id),
       complete BOOLEAN NOT NULL DEFAULT 0
);



/* Test data
*/
INSERT INTO Participants (id, participantName)
VALUES (1, 'Matthew'), (2, 'Virginie');

INSERT INTO BackingTracks (id, trackName)
VALUES (1, 'Happy Birthday'), (2, 'Dont Cry for me Argentina');

INSERT INTO Combinations (id, backingTrackId)
VALUES (1, 1);

INSERT INTO Takes (id, combinationId, takeNumber, takeName)
VALUES (1, 1, 1, 'First');

INSERT INTO Combinations (id, backingTrackId)
VALUES (2, NULL);

INSERT INTO CombinationsDetail (combinationId, takeId)
VALUES (2, 1);

INSERT INTO Takes (id, combinationId, takeNumber, takeName)
VALUES (2, 2, 2, 'Second');

