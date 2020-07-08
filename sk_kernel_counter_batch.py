#!/usr/bin/env python3

"""
==============================================================================
==============================================================================
========================       SK Kernel Counter      ========================
==============================================================================
==============================================================================

This script attempts to segment individual kernels from a scanned maize ear 
and group kernels by fluorescence. Output will be location and fluorescence 
category for each kernel. The script uses image processing functions from 
sci-kit image, as well as k-means clustering for fluorescence grouping from 
sci-kit learn.
"""

import sys
import os
import argparse

import numpy as np
import matplotlib.pyplot as plt

from scipy import ndimage as ndi
from scipy.ndimage import gaussian_filter
from skimage import img_as_float
from skimage import io
from skimage import morphology
from skimage.segmentation import watershed
from skimage import img_as_ubyte
from skimage import exposure
from skimage.measure import regionprops
from skimage.color import label2rgb
from skimage.color import rgb2gray
from skimage.morphology import reconstruction
from skimage.morphology import binary_opening
from skimage.morphology import disk
from skimage.filters import sobel
from sklearn.cluster import KMeans

"""
========================
Setting up the arguments
========================
"""

parser = argparse.ArgumentParser(description='Given maize ear scans, count the kernels and separate by color.')

parser.add_argument('-i', '--input_directory_path', type=str, help='Path of input directory. All .png files in the directory will be kernel counted.')
parser.add_argument('-p', '--image_crop_percentage', type=float, default=0.15, help='Percent width of image to crop from each side. Between 0 and 0.5.')
parser.add_argument('-d', '--h_dome_value', type=float, default=0.3, help='Isolate regional maxima with height h. Between 0 and 1.')
parser.add_argument('-wl', '--watershed_low', type=int, default=20, help='Low cutoff for the watershed transform markers (see --watershed_high).')
parser.add_argument('-wh', '--watershed_high', type=int, default=80, help='High cutoff for the watershed transform markers (see --watershed_low).')

args = parser.parse_args()


"""
===================
Crop edges function
===================

Crops the right and left sides of an image based on the argument "percent" (0-0.5)
"""

def crop_edges(input_image, input_percent):
    image = input_image
    percent = input_percent

    crop_column_width = image.shape[1]

    left_crop_column = int(round(percent * crop_column_width))
    right_crop_column =  int(round(crop_column_width - (percent * crop_column_width)))

    cropped_image = image[:, left_crop_column:right_crop_column]

    return cropped_image


"""
===============================
Filter regional maxima function
===============================

(Adapted from scikit-image.org/docs/dev/auto_examples/color_exposure/plot_regional_maxima.html)

Here, we use morphological reconstruction to create a background image, which
we can subtract from the original image to isolate bright features (regional
maxima).

Instead of creating a seed image with maxima along the image border, we can
use the features of the image itself to seed the reconstruction process.
Here, the seed image is the original image minus a fixed value, ``h``.

The final result is known as the h-dome of an image since this tends to 
isolate regional maxima of height ``h``. This operation is particularly useful 
when your images are unevenly illuminated.

h input refers to the h-dome parameter. 0.5 is a good place to start.
"""

def filter_regional_maxima(input_image, input_h):
    # Converting input image to float. Important for subtraction later, which 
    # won't work with uint8.
    image = img_as_float(input_image)

    # Extracting only the blue channel from the image. There's less variation in 
    # the brightness in this channel.
    image = image[:,:,2]

    # --------------------------------------------------------------------------
    # # For testing (sets other channels to zero instead of extracting channel):
    # image[:,:,0] = 0
    # image[:,:,2] = 0
    # io.imsave("{path]/image_green.png", image)
    # --------------------------------------------------------------------------

    # Calculating the h-dome
    image = gaussian_filter(image, 1)
    h = input_h
    seed = image - h
    mask = image
    dilated = reconstruction(seed, mask, method='dilation')
    hdome = image - dilated

    return hdome


"""
==================================
Region-based segmentation function
==================================

(Adapted from scikit-image.org/docs/dev/auto_examples/xx_applications/plot_coins_segmentation.html)

Here we segment objects from a background using the watershed transform.

Input should be hdome, the output from the Filter regional maxima function.

The marker_low and marker_high parameters determin which levels of the 
histogram become the background and which become the kernels.

So far I've been using (this will likely vary by image):
marker_low = 20
marker_high = 80
"""

def region_based_segmentation(input_hdome, marker_low, marker_high):
    hdome = input_hdome

    # Adjusting the output from filtering regional maxima
    hdome = rgb2gray(hdome) # Converting the output to grayscale
    hdome = img_as_ubyte(hdome) # Converting the float64 output to uint8

    # -----------------------------------------------------------------------------
    # For testing, this shows a histogram of the grayscale image:
    # hist = np.histogram(image, bins=np.arange(0, 256))
    # fig, axes = plt.subplots(1, 2, figsize=(8, 3))
    # axes[0].imshow(hdome, cmap=plt.cm.gray, interpolation='nearest')
    # axes[0].axis('off')
    # axes[1].plot(hist[1][:-1], hist[0], lw=2)
    # axes[1].set_title('histogram of gray values')
    # -----------------------------------------------------------------------------

    # After converting the output to uint8, the histogram is still heavily skewed 
    # to the left. Rescaling the intenity of the image slightly fixes the skew.
    hdome = exposure.rescale_intensity(hdome)

    # First, we find an elevation map using the Sobel gradient of the image.
    elevation_map = sobel(hdome)

    # Next we find markers of the background and the coins based on the extreme
    # parts of the histogram of gray values.
    markers = np.zeros_like(hdome)
    markers[hdome < marker_low] = 1 
    markers[hdome > marker_high] = 2 

    # We use the watershed transform to fill regions of the elevation map starting 
    # from the markers determined above:
    segmentation = watershed(elevation_map, markers)

    # Filling the holes in the segments, labeling them, and making a pretty overlay.
    segmentation = ndi.binary_fill_holes(segmentation - 1)

    # Doing a morphological opening to get rid of some of the bridges between 
    # segments. I need to add a function that only does this on segments that 
    # are a certain dimension, aka sig. longer than they are tall. If I do 
    # this too aggressively, the smaller segments get removed.
    segmentation = binary_opening(segmentation, selem=disk(5))

    labeled_image, _ = ndi.label(segmentation)

    return labeled_image


"""
===================================================
Remove segments that touch the bottom edge function
===================================================

In order to avoid double counting kernels that are half on the top of the 
image and half on the bottom of the image, this function removes any segments 
that touch the bottom edge of the image. Input is the labeled_image mask 
from region_based_segmentation.
"""

def remove_bottom_edge(labeled_image_mask):
    mask = labeled_image_mask

    for object_num in range(1, (np.max(mask) + 1)):
        if object_num in mask[(mask.shape[0] - 1),:]:
            mask[mask == object_num] = 0

    return mask


"""
============================
Find segment center function
============================

Finds the centers of each object in the segmentation mask, as outputted by 
ndimage watershed transform segmentation (see Region based segmentation function)
"""

def find_centers(input_array):
    array = input_array

    # I think it's converting the first 'array' to just 0 or 1, then takes the 
    # index from the second 'array.' Supposedly if the third argument is not 
    # supplied then it will use all labels greater than zero, but it's not doing 
    # that for me, so here I pull out a list of all the labels to use as the index.
    centers = ndi.center_of_mass(array, array, list(range(1, array.max() + 1)))

    # Removes entries in the list that contain NaN (comes from segments getting 
    # deleted in remove_bottom_edge).
    centers_no_nan = [x for x in centers if str(x[0]) != 'nan']

    return centers_no_nan


"""
===========================
Get mean intensity function
===========================

Finds the mean intensity in each channel (RGB) for each object in a mask. 

Note: if you are using a cropped image to do the segmentation, make sure you 
input the same cropped image in this function, not the uncropped image.
"""

def mean_intensity(input_image, input_mask):
    red_image = input_image[:,:,0]
    green_image = input_image[:,:,1]
    blue_image = input_image[:,:,2]

    mask = input_mask

    output_red_intensity = list()
    output_green_intensity = list()
    output_blue_intensity = list()

    for object_num in range(1, (np.max(mask) + 1)):
        if object_num in mask:
            red_mean_intensity = np.mean(red_image[mask == object_num])
            green_mean_intensity = np.mean(green_image[mask == object_num])
            blue_mean_intensity = np.mean(blue_image[mask == object_num])

            output_red_intensity.append(red_mean_intensity)
            output_green_intensity.append(green_mean_intensity)
            output_blue_intensity.append(blue_mean_intensity)

    rgb_intensity = np.column_stack((output_red_intensity,
                                     output_green_intensity, 
                                     output_blue_intensity))

    return rgb_intensity


"""
==========================
Calculate k-means function
==========================

Performs k-means clustering with two clusters on rgb intensity values (output 
from Get mean intensity function). Just a wrapper for sklearn Kmeans.
"""

def kmeans_from_rgb(rgb_input):
    rgb = rgb_input
    kmeans = KMeans(n_clusters=2).fit(rgb)

    return kmeans


"""
============================
Which is more green function
============================

K-means clustering does a good job of separating the rgb intensity values into 
two groups, but the group labels depend on the random starting positions of 
the two clusters. For labeling the image, I want to know which cluster is the 
green fluorescent kernels and which cluster is the rest. This function takes 
the Calculate k-means fuction output as its input. It returns the k-means with
kmeans.labels_ formatted like this:

0 = green
1 = not green
"""

def which_is_more_green(rgb_input, kmeans_input):
    kmeans = kmeans_input

    # Calculating the mean green intensity of all the values in each label
    all_green_intensity = rgb_input[:,1]

    label_0_green_mean = np.mean(all_green_intensity[[not i for i in kmeans_input.labels_]])
    label_1_green_mean = np.mean(all_green_intensity[kmeans_input.labels_])

    # Since 0 is green, if 0 is already set to green then no problem. 
    # Otherwise it will flip the values in kmeans.labels_.
    if label_0_green_mean < label_1_green_mean:
        labels = kmeans.labels_

        # This isn't pretty, but I couldn't figure out a better way
        labels[labels == 0] = 3
        labels[labels == 1] = 0
        labels[labels == 3] = 1

        # Replacing the original labels with the new ones
        kmeans.labels_ = labels

    return(kmeans)



"""
==========================================
Putting it all together in a meta-function
==========================================
"""

def count_kernels(input_image, crop_percentage, h_dome_value, watershed_low, watershed_high):
    # Importing and cropping the image (older version below)
    raw_image = io.imread(input_image)
    image = crop_edges(raw_image, crop_percentage)

    # Getting the regional maxima
    hdome = filter_regional_maxima(image, h_dome_value)

    # Doing the segmentation
    image_segments = region_based_segmentation(hdome, watershed_low, watershed_high)

    # Removing segments that touch bottom edge to avoid double counting
    image_segments = remove_bottom_edge(image_segments)

    # Finding the centers of the segments
    segment_centers = find_centers(image_segments)

    # Getting the mean rgb intensity
    rgb_intensity = mean_intensity(image, image_segments)

    # K-means clustering of RGB intensity values (should split segments into 
    # fluorescent and non-fluorescent groups)
    # Fixes an error where no segments were predicted in some images
    if(rgb_intensity.shape[0] == 0):
        return([0, 0])
    kmeans = kmeans_from_rgb(rgb_intensity)

    # This makes sure that the fluorescent cluster is labeled consistently
    kmeans = which_is_more_green(rgb_intensity, kmeans)

    # Making an ndarray with coordinates and labels
    centers_y, centers_x = zip(*segment_centers)
    centers_y = np.asarray(centers_y)
    centers_x = np.asarray(centers_x)
    labels = kmeans.labels_
    data_array = np.column_stack((centers_x, centers_y, labels))

    # For now, just counting the total number of each type of kernel
    unique, counts = np.unique(data_array[:, [2]], return_counts = True)
    # output_counts = dict(zip(unique, counts))

    return(counts)



"""
==================================================
Running the function on a directory full of images
==================================================
"""

# Setting up the list of image paths
input_directory = args.input_directory_path
input_image_list = []

for file in os.listdir(input_directory):
    if file.endswith('.png'):
        input_image_list.append(os.path.join(input_directory, file))

# Running the kernel counter on each image
image_name_list = []
fluor_kernel_count = []
nonfluor_kernel_count = []

for image in input_image_list:
    image_name_list.append(os.path.splitext(os.path.split(image)[1])[0])
    count_kernels_output = count_kernels(image, 
                                         args.image_crop_percentage, 
                                         args.h_dome_value,
                                         args.watershed_low,
                                         args.watershed_high)
    fluor_kernel_count.append(count_kernels_output[0])
    nonfluor_kernel_count.append(count_kernels_output[1])
    print(image + " processed" + "\n")

# Writing the results to a tsv file
output_file = open('sk_kernel_counter_batch_output.tsv', 'w+')
output_list = []

for counter, image in enumerate(image_name_list):
    line = (str(image) + 
           '\t' +
           str(fluor_kernel_count[counter]) +
           '\t' +
           str(nonfluor_kernel_count[counter]))
    output_list.append(line)

output_file.write('\n'.join(output_list))
output_file.close()

