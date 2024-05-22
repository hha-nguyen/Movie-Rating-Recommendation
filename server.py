import time, sys, cherrypy, os
from paste.translogger import TransLogger
from app import create_app
from pyspark import SparkContext, SparkConf
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_spark_context():
    try:
        # Load Spark context
        conf = SparkConf().setAppName("movie_recommendation-server") \
                          .setMaster("local[*]") \
                          .set("spark.driver.memory", "4g") \
                          .set("spark.executor.memory", "4g")
        # IMPORTANT: Pass additional Python modules to each worker
        sc = SparkContext(conf=conf, pyFiles=['engine.py', 'app.py'])
        logger.info("Spark context initialized successfully")
        return sc
    except Exception as e:
        logger.error("Error initializing Spark context: %s", str(e))
        sys.exit(1)
 
 
def run_server(app):
    try:
        # Enable WSGI access logging via Paste
        app_logged = TransLogger(app)
        # Mount the WSGI callable object (app) on the root directory
        cherrypy.tree.graft(app_logged, '/')
        # Set the configuration of the web server
        cherrypy.config.update({
            'engine.autoreload.on': True,
            'log.screen': True,
            'server.socket_port': int(os.getenv('SERVER_PORT', 5000)),
            'server.socket_host': os.getenv('SERVER_HOST', '127.0.0.1')
        })
        # Start the CherryPy WSGI web server
        logger.info("Starting CherryPy web server on %s:%s", 
                    cherrypy.config['server.socket_host'], 
                    cherrypy.config['server.socket_port'])
        cherrypy.engine.start()
        cherrypy.engine.block()
    except Exception as e:
        logger.error("Error running the server: %s", str(e))
        sys.exit(1)

 
 
if __name__ == "__main__":
    try:
        # Init Spark context and load libraries
        sc = init_spark_context()
        dataset_path = os.path.join('datasets', 'ml-latest')
        db_url = os.getenv('DATABASE_URL', 'postgresql://postgres:Ha29082002@localhost:5432/watchlist')
        app = create_app(sc, dataset_path, db_url)
        # Start web server
        run_server(app)
    except Exception as e:
        logger.error("Error in main execution: %s", str(e))
        sys.exit(1)

