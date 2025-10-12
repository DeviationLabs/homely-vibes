#!/usr/bin/env python3
# coding: utf-8
# from https://towardsdatascience.com/keras-transfer-learning-for-beginners-6c9b8b7143e

import argparse
import pickle
import os
import re

parser = argparse.ArgumentParser(description="Transfer learning on imagenet model")
parser.add_argument("--train_dir", help="Folder with training images", default="./train")
parser.add_argument(
    "--training_epochs",
    help="Epochs to use for training mode. Recommend: 5, Default: 1",
    type=int,
    choices=range(1, 10),
    default=1,
)
parser.add_argument("--model_file", help="Trained model", default="my_model.h5")
args = parser.parse_args()

num_preds = 0
if os.path.isdir(args.train_dir):
    num_preds = sum(
        os.path.isdir("%s/%s" % (args.train_dir, i)) for i in os.listdir(args.train_dir)
    )
if num_preds == 0:
    raise ValueError("Error reading data in training directory: %s" % args.train_dir)

# In[1]:
import tensorflow as tf
from keras.layers import Dense, GlobalAveragePooling2D
from keras.applications import MobileNet
from keras.applications.mobilenet import preprocess_input
from keras.preprocessing.image import ImageDataGenerator
from keras.models import Model

tf.logging.set_verbosity(tf.logging.ERROR)
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"


# In[2]:
base_model = MobileNet(
    weights="imagenet", include_top=False, input_shape=(224, 224, 3)
)  # imports the mobilenet model and discards the last 1000 neuron layer.

x = base_model.output
x = GlobalAveragePooling2D()(x)
x = Dense(
    1024, activation="relu"
)(
    x
)  # we add dense layers so that the model can learn more complex functions and classify for better results.
x = Dense(1024, activation="relu")(x)  # dense layer 2
x = Dense(512, activation="relu")(x)  # dense layer 3
preds = Dense(num_preds, activation="softmax")(
    x
)  # final layer with softmax activation # soft max predictions over the number of outcomes.

# In[3]:
for layer in base_model.layers[:20]:
    layer.trainable = False
for layer in base_model.layers[20:]:
    layer.trainable = True
model = Model(inputs=base_model.input, outputs=preds)

# In[4]:
# for layer in model.layers[:20]:
#    layer.trainable=False
# for layer in model.layers[20:]:
#    layer.trainable=True

# In[5]:
train_datagen = ImageDataGenerator(
    preprocessing_function=preprocess_input
)  # included in our dependencies

print("Start training on dir: %s" % args.train_dir)
train_generator = train_datagen.flow_from_directory(
    args.train_dir,  # the path to the main data folder
    target_size=(224, 224),
    color_mode="rgb",
    batch_size=32,
    class_mode="categorical",
    shuffle=True,
)


# In[33]:
model.compile(optimizer="Adam", loss="categorical_crossentropy", metrics=["accuracy"])

step_size_train = train_generator.n // train_generator.batch_size
model.fit_generator(
    generator=train_generator,
    steps_per_epoch=step_size_train,
    epochs=args.training_epochs,
)
model_labels = train_generator.class_indices

print("Saving to file: %s" % args.model_file)
model.save(args.model_file)
with open(re.sub(r".h5$", ".pickle", args.model_file), "wb") as pickle_file:
    pickle.dump(model_labels, pickle_file)
model.summary()

# Check if this still making sense..
score = model.evaluate_generator(train_generator, 10)
print("Loss: ", score[0], "Accuracy: ", score[1])

print("Done!")
