class SessionFiles:
    def __init__(self, root_dir):
        # Define directories
        self.session_dir = root_dir / "session_files"
        self.uploads_dir = self.session_dir / "uploads"
        self.tracks_dir = self.session_dir / "tracks"
        self.takes_dir = self.session_dir / "takes"

        # Ensure directories exist
        self.session_dir.mkdir(exist_ok=True)
        self.uploads_dir.mkdir(exist_ok=True)
        self.tracks_dir.mkdir(exist_ok=True)
        self.takes_dir.mkdir(exist_ok=True)

        # Database needs to be set once it's created
        self._db = None

    def set_database(self, db):
        self._db = db

    def get_track_path(self, track_id):
        return self.tracks_dir / f"{track_id:03d}.opus"

    def get_take_path(self, take_id):
        return self.takes_dir / f"{take_id:03d}.opus" 

    def get_track_relpath(self, track_id):
        path = self.get_track_path(track_id)
        return path.relative_to(self.session_dir)
    
    def get_take_relpath(self, take_id):
        path = self.get_take_path(take_id)
        return path.relative_to(self.session_dir)
