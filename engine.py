import os
from pyspark.mllib.recommendation import ALS
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base = declarative_base()

class Movie(Base):
    __tablename__ = 'movie'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    
def get_counts_and_averages(ID_and_ratings_tuple):
    """Given a tuple (movieID, ratings_iterable) 
    returns (movieID, (ratings_count, ratings_avg))
    """
    nratings = len(ID_and_ratings_tuple[1])
    return ID_and_ratings_tuple[0], (nratings, float(sum(x for x in ID_and_ratings_tuple[1]))/nratings)


class RecommendationEngine:

    def __count_and_average_ratings(self):
        logger.info("Counting movie ratings...")
        movie_ID_with_ratings_RDD = self.ratings_RDD.map(lambda x: (x[1], x[2])).groupByKey()
        movie_ID_with_avg_ratings_RDD = movie_ID_with_ratings_RDD.map(get_counts_and_averages)
        self.movies_rating_counts_RDD = movie_ID_with_avg_ratings_RDD.map(lambda x: (x[0], x[1][0]))


    def __train_model(self):
        logger.info("Training the ALS model...")
        self.model = ALS.train(self.ratings_RDD, self.rank, seed=self.seed,
                               iterations=self.iterations, lambda_=self.regularization_parameter)
        logger.info("ALS model built!")


    def __predict_ratings(self, user_and_movie_RDD):
        predicted_RDD = self.model.predictAll(user_and_movie_RDD)
        predicted_rating_RDD = predicted_RDD.map(lambda x: (x.product, x.rating))
        predicted_rating_title_and_count_RDD = \
            predicted_rating_RDD.join(self.movies_titles_RDD).join(self.movies_rating_counts_RDD)
        predicted_rating_title_and_count_RDD = \
            predicted_rating_title_and_count_RDD.map(lambda r: (r[1][0][1], r[1][0][0], r[1][1]))
        
        return predicted_rating_title_and_count_RDD
    
    def add_ratings(self, ratings):
        # Convert ratings to an RDD
        new_ratings_RDD = self.sc.parallelize(ratings)
        # Add new ratings to the existing ones
        self.ratings_RDD = self.ratings_RDD.union(new_ratings_RDD)
        # Re-compute movie ratings count
        self.__count_and_average_ratings()
        self.__train_model()
        
        return ratings

    def get_ratings_for_movie_ids(self, user_id, movie_ids):
        requested_movies_RDD = self.sc.parallelize(movie_ids).map(lambda x: (user_id, x))
        # Get predicted ratings
        ratings = self.__predict_ratings(requested_movies_RDD).collect()

        return ratings
    
    def get_top_ratings(self, user_id, movies_count):
        # Predict ratings for all movies
        all_movies_ids = [movie_id for movie_id, _ in self.movies_titles_RDD.collect()]
        all_movies_RDD = self.sc.parallelize(all_movies_ids).map(lambda x: (user_id, x))
        all_predicted_ratings = self.__predict_ratings(all_movies_RDD).collect()

        # Filter predicted ratings for movies present in the database
        session = self.Session()
        db_movies = session.query(Movie).all()
        db_movie_ids = {movie.title: movie.id for movie in db_movies}
        session.close()

        filtered_ratings = [(title, rating) for title, rating, _ in all_predicted_ratings if title in db_movie_ids]

        # Sort by rating in descending order
        sorted_ratings = sorted(filtered_ratings, key=lambda x: -x[1])

        # Limit to top movies_count
        top_ratings = sorted_ratings[:movies_count]

        return top_ratings
    
    def __init__(self, sc, dataset_path, db_url):
        logger.info("Starting up the Recommendation Engine: ")

        self.sc = sc
         # Initialize database connection
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        # Load ratings data for later use
        logger.info("Loading Ratings data...")
        ratings_file_path = os.path.join(dataset_path, 'ratings.csv')
        ratings_raw_RDD = self.sc.textFile(ratings_file_path)
        ratings_raw_data_header = ratings_raw_RDD.take(1)[0]
        self.ratings_RDD = ratings_raw_RDD.filter(lambda line: line!=ratings_raw_data_header)\
            .map(lambda line: line.split(",")).map(lambda tokens: (int(tokens[0]),int(tokens[1]),float(tokens[2]))).cache()
        # Load movies data for later use
        logger.info("Loading Movies data...")
        movies_file_path = os.path.join(dataset_path, 'movies.csv')
        movies_raw_RDD = self.sc.textFile(movies_file_path)
        movies_raw_data_header = movies_raw_RDD.take(1)[0]
        self.movies_RDD = movies_raw_RDD.filter(lambda line: line!=movies_raw_data_header)\
            .map(lambda line: line.split(",")).map(lambda tokens: (int(tokens[0]),tokens[1],tokens[2])).cache()
        self.movies_titles_RDD = self.movies_RDD.map(lambda x: (int(x[0]),x[1])).cache()
        # Pre-calculate movies ratings counts
        self.__count_and_average_ratings()

        # Train the model
        self.rank = 8
        self.seed = 5
        self.iterations = 10
        self.regularization_parameter = 0.1
        self.__train_model() 
