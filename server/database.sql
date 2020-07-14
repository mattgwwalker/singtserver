/* Enable Foreign Keys.  This needs to be executed for each databse
connection as it feaults to disabled. */

PRAGMA foreign_keys = ON;


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


/* Create the Takes table.  A Take is based on either a backing track,
or another take, or one of each.  Takes maybe aborted part way
through, in which case they are not considered complete. */

CREATE TABLE Takes (
       id INTEGER PRIMARY KEY,
       backingTrackId INTEGER,
       takeId INTEGER REFERENCES Takes(id),
       takeNumber INTEGER NOT NULL,
       complete BOOLEAN NOT NULL DEFAULT 0,
       FOREIGN KEY(backingTrackId) REFERENCES BackingTracks(id),
       --FOREIGN KEY(takeId) REFERENCES Takes(id),
       CHECK (backingTrackId IS NOT NULL OR takeId IS NOT NULL) -- at least one of them must be set
);


/* Create the Recordings table.  Participants create recordings that
are associated with a given take. */

CREATE TABLE Recordings (
       id INTEGER PRIMARY KEY,
       participantId INTEGER NOT NULL,
       takeId INTEGER NOT NULL,
       FOREIGN KEY(participantId) REFERENCES Participants(id),
       FOREIGN KEY(takeId) REFERENCES Takes(id)
);



/* Test data */
INSERT INTO Participants (participantName)
VALUES ("Matthew");
INSERT INTO Participants (participantName)
VALUES ("Virginie");

INSERT INTO BackingTracks (trackName)
VALUES ("Happy Birthday");
INSERT INTO BackingTracks (trackName)
VALUES ("Don't Cry for me Argentina");
