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

    def get_track_filename(self, track_id):
        return self.tracks_dir / f"{track_id:03d}.opus"

    def get_take_filename(self, take_id):
        return self.takes_dir / f"{take_id:03d}.opus" 
