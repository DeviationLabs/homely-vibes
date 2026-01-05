#!/usr/bin/env python3

from typing import Any, Tuple, Dict
import argparse
import matplotlib.pyplot as plt
import numpy as np
import cv2
import os
import pickle
import re
import tensorflow as tf
import keras
from keras.applications.mobilenet import preprocess_input
from keras.models import load_model
from keras.preprocessing import image
from keras.preprocessing.image import ImageDataGenerator
from keras.utils.generic_utils import CustomObjectScope
from lib.config import get_config

tf.logging.set_verbosity(tf.logging.ERROR)
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"


def load_my_model(model_file: str) -> Tuple[Any, Dict[str, int]]:
    with open(re.sub(r".h5$", ".pickle", model_file), "rb") as pickle_file:
        model_labels = pickle.load(pickle_file)

    print("Loading model: %s" % model_file)
    with CustomObjectScope(
        {
            "relu6": keras.applications.mobilenet.relu6,
            "DepthwiseConv2D": keras.applications.mobilenet.DepthwiseConv2D,
        }
    ):
        model = load_model(model_file)
    print("Done")
    return (model, model_labels)


def run_predictor(model: Any, model_labels: Dict[str, int], img: Any) -> Tuple[str, str]:
    cfg = get_config()
    x = image.img_to_array(img)
    x = cv2.resize(x, dsize=(224, 224), interpolation=cv2.INTER_CUBIC)
    x = np.expand_dims(x, axis=0)
    x = preprocess_input(x)
    y_pred1 = model.predict(x, verbose=1)

    best_guess_index = np.argmax(y_pred1, axis=-1)[0]
    for key, val in model_labels.items():
        if val == best_guess_index:
            best_guess_label = key
    msg = "Best Guess: %s (Confidence: %0.2f)  -- " % (
        best_guess_label,
        y_pred1[0][best_guess_index],
    )
    msg += np.array2string(y_pred1[0], precision=2, separator=",", suppress_small=True)
    return best_guess_label, msg


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TF packages validator and one shot image prediction"
    )
    parser.add_argument("--predict_file", help="image to run prediction", default="dummy.jpg")
    parser.add_argument(
        "--display_image",
        help="Show image to be predicted",
        action="store_true",
        default=False,
    )
    parser.add_argument("--model_file", help="Trained model", default="my_model.h5")
    parser.add_argument("--train_dir", help="Folder with training images", default=None)
    args = parser.parse_args()

    # tf.enable_eager_execution()
    # tf.compat.v1.disable_eager_execution()
    try:
        tf.reduce_sum(tf.random_normal([1000, 1000]))
    except Exception:
        raise
    print("Success with tensorflow dryrun. All packages validated !!")

    predicted = False
    model, model_labels = None, None
    if os.path.isfile(args.model_file):
        model, model_labels = load_my_model(args.model_file)

    if model is not None and args.train_dir is not None:
        print("Recheck model on training dir: %s" % args.train_dir)
        train_datagen = ImageDataGenerator(
            preprocessing_function=preprocess_input
        )  # included in our dependencies
        train_generator = train_datagen.flow_from_directory(
            args.train_dir,  # the path to the main data folder
            target_size=(224, 224),
            color_mode="rgb",
            batch_size=32,
            class_mode="categorical",
            shuffle=True,
        )
        score = model.evaluate_generator(train_generator, 10)
        print("Loss: ", score[0], "Accuracy: ", score[1])

        # Two images from our library that should show an outcome
        img = image.load_img(
            "%s/image_classification/train_animals/horses/images.jpg" % cfg.paths.home
        )
        label, msg = run_predictor(model, model_labels, img)
        print(msg)
        img = image.load_img(
            "%s/image_classification/train_garage/door_open/Garage_2019-01-28_07-55-39.jpg"
            % cfg.paths.home
        )
        label, msg = run_predictor(model, model_labels, img)
        print(msg)

    if os.path.isfile(args.predict_file) and model is not None:
        print("Predicting image: %s" % args.predict_file)
        img = image.load_img(args.predict_file)
        label, msg = run_predictor(model, model_labels, img)
        print(msg)
        predicted = True
        if args.display_image:
            plt.ion()
            plt.imshow(img)
            plt.show()
            plt.pause(0.1)
            print("Press <Enter> to terminate..")
            input()

    print("Done!")
