"""Serializable command and repository snapshots."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    stdout: str
    stderr: str
    returncode: int
    files: dict
    state: dict
    git: dict

    def to_dict(self):
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "files": self.files,
            "state": self.state,
            "git": self.git,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            stdout=data["stdout"],
            stderr=data["stderr"],
            returncode=int(data["returncode"]),
            files=dict(data["files"]),
            state=dict(data["state"]),
            git=dict(data["git"]),
        )
