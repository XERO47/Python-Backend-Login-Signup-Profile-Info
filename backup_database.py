import os
import subprocess
from datetime import datetime

from pymongo import MongoClient

# MongoDB configuration
mongo_uri = "mongodb://localhost:27017"  # Replace with your MongoDB URI
database_name = "flightest"  # Replace with your database name
output_dir = "./"  # Replace with the desired backup folder path

def backup_mongodb_database():
    # Create a timestamped folder for the backup
    backup_folder = os.path.join(output_dir, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(backup_folder, exist_ok=True)

    try:
        # Use the subprocess module to run the mongodump command
        subprocess.run(["mongodump", "--uri", mongo_uri, "--db", database_name, "--out", backup_folder])

        print("MongoDB backup completed successfully.")
    except FileNotFoundError:
        print("Error: mongodump command not found. Make sure MongoDB Tools are installed.")
    except subprocess.CalledProcessError as e:
        print(f"Error while running mongodump: {e}")

if __name__ == "__main__":
    backup_mongodb_database()
