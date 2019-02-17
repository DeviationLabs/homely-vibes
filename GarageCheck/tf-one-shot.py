#!/usr/bin/env python3.5

import argparse
import numpy as np
import matplotlib
import os.path
import pandas
import pickle
import PIL.Image
import re
import scipy

parser = argparse.ArgumentParser(description = "TF packages validator and one shot image prediction")
parser.add_argument('--predict',
                      help    ='image to run prediction',
                      default ='dummy.jpg')
parser.add_argument('--model_file',
                      help    ='Trained model',
                      default ='my_model.h5')
args = parser.parse_args()

import tensorflow as tf
import keras
from keras.models import load_model
from keras.preprocessing import image
from keras.utils.generic_utils import CustomObjectScope


def run_predictor(model, model_labels, image_file):
  img = image.load_img(image_file, target_size=(224, 224))
  x = image.img_to_array(img)
  x = np.expand_dims(x, axis=0)
  y_pred1= model.predict(x)

  print (y_pred1)
  best_guess = model_labels[np.argmax(y_pred1,axis=-1)]
  print ("Best Guess: %s" % best_guess)
  return best_guess

if __name__ == "__main__":
  #tf.enable_eager_execution()
  #tf.compat.v1.disable_eager_execution()
  tf.logging.set_verbosity(tf.logging.ERROR)
  os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
  print(tf.reduce_sum(tf.random_normal([1000, 1000])))
  print("Success with tensorflow dryrun. All packages validated !!")

  if os.path.isfile(args.model_file):
    model_labels = None
    model = None

    with open(re.sub(r".h5$", ".pickle", args.model_file), "rb") as pickle_file:
      model_labels = pickle.load(pickle_file)

    print("Loading model: %s" % args.model_file)
    with CustomObjectScope({'relu6': keras.applications.mobilenet.relu6,
                            'DepthwiseConv2D': keras.applications.mobilenet.DepthwiseConv2D}):
      model = load_model(args.model_file)
      print("Compiling model ...")
      model.compile(optimizer='Adam',
                  loss='categorical_crossentropy',
                  metrics=['accuracy'])
    print("Done")

    if os.path.isfile(args.predict):
      print("Predicting image: %s" % args.predict)
      output = run_predictor(model, model_labels, args.predict)
      predicted = True

  if not predicted:
    print("Invalid argument options. Skipped predictions")
