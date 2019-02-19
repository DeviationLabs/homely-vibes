#!/usr/bin/env python3.6

import argparse
import matplotlib.pyplot as plt
import numpy as np
import cv2
import os
import pickle
import re
import tensorflow as tf
import keras
from keras.models import load_model
from keras.preprocessing import image
from keras.utils.generic_utils import CustomObjectScope

tf.logging.set_verbosity(tf.logging.ERROR)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

def load_my_model(model_file):
  with open(re.sub(r".h5$", ".pickle", model_file), "rb") as pickle_file:
    model_labels = pickle.load(pickle_file)

  print("Loading model: %s" % model_file)
  with CustomObjectScope({'relu6': keras.applications.mobilenet.relu6,
                          'DepthwiseConv2D': keras.applications.mobilenet.DepthwiseConv2D}):
    model = load_model(model_file)
    print("Compiling model ...")
    model.compile(optimizer='Adam',
                  loss='categorical_crossentropy',
                  metrics=['accuracy'])
  print("Done")
  return (model, model_labels)

def run_predictor(model, model_labels, img):
  img = cv2.resize(img, dsize=(224, 224), interpolation=cv2.INTER_CUBIC)
  x = image.img_to_array(img)
  x = np.expand_dims(x, axis=0)
  y_pred1= model.predict(x)

  best_guess_index = np.argmax(y_pred1,axis=-1)[0]
  for key, val in model_labels.items():
    if val == best_guess_index:
      best_guess_label = key
  msg = "Best Guess: %s (Confidence: %0.2f)  -- " % (best_guess_label, y_pred1[0][best_guess_index])
  msg += np.array2string(y_pred1[0], precision=2, separator=',', suppress_small=True)
  return best_guess_label, msg

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description = "TF packages validator and one shot image prediction")
  parser.add_argument('--predict_file',
                        help    ='image to run prediction',
                        default ='dummy.jpg')
  parser.add_argument('--model_file',
                        help    ='Trained model',
                        default ='my_model.h5')
  args = parser.parse_args()

  #tf.enable_eager_execution()
  #tf.compat.v1.disable_eager_execution()
  print(tf.reduce_sum(tf.random_normal([1000, 1000])))
  print("Success with tensorflow dryrun. All packages validated !!")

  predicted = False
  if os.path.isfile(args.model_file):
    model, model_labels = load_my_model(args.model_file)

    if os.path.isfile(args.predict_file):
      print("Predicting image: %s" % args.predict_file)
      img = image.load_img(args.predict_file)
      plt.ion()
      plt.imshow(img) ## TODO: not working?
      plt.show()
      plt.pause(0.1)
      label, msg = run_predictor(model, model_labels, img)
      print(msg)
      predicted = True

  if not predicted:
    print("Invalid argument options. Skipped predictions")
