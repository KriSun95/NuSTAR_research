#!/bin/python3

import datetime
import sunpy.map
import astropy.units as u
import matplotlib.pyplot as plt
import matplotlib.patches as patches # for rectangles in Sunpy V3.1.0, I can't get draw_rectangle() to work
#import nustar_pysolar # for solar to RA/Dec coordinate transform
import numpy as np

from reproject import reproject_interp
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
from sunpy.coordinates import Helioprojective, RotatedSunFrame, transform_with_sun_center
from sunpy.net import Fido, attrs as a
from aiapy.calibrate import register, update_pointing, normalize_exposure

import warnings
warnings.filterwarnings("ignore")


# Define constants
X_LABEL = 'X (arcseconds)'
Y_LABEL = 'Y (arcseconds)'
AIA_WAVELENGTH = 94 # Units of angstroms
STEREO_MIN_WAVELENGTH = 171 # Units of angstroms
STEREO_MAX_WAVELENGTH = 211 # Units of angstroms


def most_recent_map(_map):
    """
    Query and return the most recent _map (of "AIA" or "STEREO") 
    that Sunpy.Fido can get.
    
    Parameters
    ----------
    _map : string
        The instrument you want the most recent map from. 
        E.g., _map="aia" or _map="stereo". 
        
    Returns
    -------
    Sunpy generic map.
    """
    
    if _map.lower()=="aia":
        info = (a.Instrument("aia") & a.Wavelength(AIA_WAVELENGTH*u.angstrom))
        look_back = {"days":2}
    elif _map.lower()=="stereo":
        info = (a.Source('STEREO_A') & a.Instrument("EUVI") & \
            a.Wavelength(STEREO_MIN_WAVELENGTH*u.angstrom, STEREO_MAX_WAVELENGTH*u.angstrom)) 
        look_back = {"weeks":4}
    else:
        print("Don't know what to do! Please set _map=\"aia\" or \"stereo\".")
        
    current_date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    
    past = datetime.datetime.now()-datetime.timedelta(**look_back)
    past_date = past.strftime("%Y-%m-%dT%H:%M:%S")

    startt = str(past_date)
    endt= str(current_date)

    result = Fido.search(a.Time(startt, endt), info)
    
    file_download = Fido.fetch(result[0, -1], site='ROB')
    aiamap = sunpy.map.Map(file_download[0])
    
    return aiamap


def project_map(in_map, future_time):
    """
    Create a projection of an input map at the given input time.
    
    Parameters
    ----------
    in_map : Sunpy map
        The input map to be projected.
    future_time : str
        The time of the projected map. 
        
    Returns
    -------
    Sunpy generic map.
    """

    in_time = in_map.date
    out_frame = Helioprojective(observer='earth', obstime=future_time,
                                rsun=in_map.coordinate_frame.rsun)
    rot_frame = RotatedSunFrame(base=out_frame, rotated_time=in_time)

    out_shape = in_map.data.shape
    out_center = SkyCoord(0*u.arcsec, 0*u.arcsec, frame=out_frame)
    header = sunpy.map.make_fitswcs_header(out_shape,
                                           out_center,
                                           scale=u.Quantity(in_map.scale))
    
    out_wcs = WCS(header)
    out_wcs.coordinate_frame = rot_frame

    with transform_with_sun_center():
        arr, _ = reproject_interp(in_map, out_wcs, out_shape)
    
    out_warp = sunpy.map.Map(arr, out_wcs)
    out_warp.plot_settings = in_map.plot_settings

    return out_warp


def draw_nustar_fov(in_map, center_x, center_y, layers=[-100, 0, 100], colors='red', rotate=0, pixscale=None):
    """
    Draw squares representing NuSTAR's field of view on the current map.
    
    By default, three squares are drawn: one that is equal
    to the 12x12 arcminute FOV and two with side lengths
    of +-100 arcseconds from the actual side lengths.
    
    Parameters
    ----------
    in_map : Sunpy map
        The input map on which the squares will be overlaid.
    center_x : float
        The x position, in arcseconds, of the squares' center point.
    center_y : float
        The y position, in arcseconds, of the squares' center point.
    layers : list
        List of values, in arcseconds, containing the adjustments
        to the side lengths of the drawn squares. Each value results
        in a new square drawn on the map.
    colors : str or list of str
        The colors of the drawn squares. If colors is a string,
        then each square will be drawn with that color.
        Otherwise, a list can be provided to customize the color
        of each layer. The index of the color will match the index
        of the layer.
    rotate : int or float
        Anti-clockwise rotation from Solar north for NuSTAR field of view.
    pixscale : float
        Arcsecond-to-pixel conversion for the original AIA or STEREO map.
        Needed for the NuSTAR field of view rotation.
        
    Returns
    -------
    None
    """
    
    # Change the colors variable to a list if it's not already one.
    if not isinstance(colors, list):
        colors = [colors]*len(layers)
    
    FOV_SIDE_LENGTH = 12*60 # Units of arcseconds

    for i, diff in enumerate(layers):
        if rotate==0:
            # Translate to bottom left corner of rectangle
            bottom_left = ((center_x - FOV_SIDE_LENGTH/2 - diff)*u.arcsec,
                           (center_y - FOV_SIDE_LENGTH/2 - diff)*u.arcsec)
            rect_bl = SkyCoord(*bottom_left, frame=in_map.coordinate_frame)

            in_map.draw_quadrangle(bottom_left=rect_bl,
                                     width=(FOV_SIDE_LENGTH+2*diff)*u.arcsec,
                                     height=(FOV_SIDE_LENGTH+2*diff)*u.arcsec,
                                     color=colors[i])
        else:
            # get boxes in pixels, newer Sunpy doesn't allow draw_rectangle here
            center_pix = [in_map.data.shape[1]/2, in_map.data.shape[0]/2]
            
            # get bottom left coords in ref. frame where center of box 
            bx_arc_square, by_arc_square = -FOV_SIDE_LENGTH/2 - diff, -FOV_SIDE_LENGTH/2 - diff
            
            # rotate bottom left clockwise to find where box to-be-rotated to maintain centers needs to be
            rot_mat = np.array([[np.cos(-rotate*(np.pi/180)), np.sin(-rotate*(np.pi/180))],
                                [-np.sin(-rotate*(np.pi/180)), np.cos(-rotate*(np.pi/180))]]) @ np.array([bx_arc_square,by_arc_square])

            bx_rotarc, by_rotarc = rot_mat[0], rot_mat[1]
            
            # bottom left of new box in arcsec where cneter of the Sun is (0,0)
            bx_arc, by_arc = (center_x+bx_rotarc), (center_y+by_rotarc)
            
            # create and rotate box
            rect = patches.Rectangle([center_pix[0]+bx_arc/pixscale,
                                      center_pix[1]+by_arc/pixscale], 
                                     (FOV_SIDE_LENGTH+2*diff)/pixscale, 
                                     (FOV_SIDE_LENGTH+2*diff)/pixscale, 
                                     facecolor="none", 
                                     linewidth=2, 
                                     edgecolor=colors[i], 
                                     angle=rotate)
            
            plt.gca().add_patch(rect)


def reprojection(obstime:str, center_x, center_y, layers, rotate=0):
    """
    Creates plot of the AIA and STEREO plot of a specific time projected onto a future time.
    
    Parameters
    ----------
    obstime : string
        Time the AIA and STEREO maps should be projected to; e.g., '2021-11-10T12:00:00'.
    center_x : float
        The x position, in arcseconds, of the squares' center point.
    center_y : float
        The y position, in arcseconds, of the squares' center point.
    rotate : int or float
        Anti-clockwise rotation from Solar north for NuSTAR field of view.
        
    Returns
    -------
    Tuple of axes for each subplot created.
    """

    # For AIA.
    aiamap = most_recent_map(_map="aia")
    projected_aiamap = project_map(aiamap, obstime)
    print("Got AIA map.")

    reversed_aia_cmap = (aiamap.cmap).reversed()

    ax1 = plt.subplot(2, 2, 1, projection=aiamap)
    aiamap.plot(cmap=reversed_aia_cmap, title=f"Original AIA Map\nAIA " + \
        str(AIA_WAVELENGTH) + f" {aiamap.date}")
    ax1.set_xlabel(X_LABEL)
    ax1.set_ylabel(Y_LABEL)
    plt.colorbar(fraction=0.046, pad=0.04)

    ax2 = plt.subplot(2, 2, 2, projection=projected_aiamap)
    projected_aiamap.plot(cmap=reversed_aia_cmap, title="Reprojected to an Earth Observer\nAIA " + \
        str(AIA_WAVELENGTH) + f" {projected_aiamap.date}")
    ax2.set_xlabel(X_LABEL)
    ax2.set_ylabel(Y_LABEL)
    plt.colorbar(fraction=0.046, pad=0.04)

    draw_nustar_fov(projected_aiamap, center_x, center_y, layers, rotate=rotate, pixscale=u.Quantity(aiamap.scale).value[0])

    # For STEREO.
    stereomap = most_recent_map(_map="stereo")
    projected_stereomap = project_map(stereomap, obstime)
    print("Got STEREO-A map.")

    reversed_stereo_cmap = (stereomap.cmap).reversed()

    ax3 = plt.subplot(2, 2, 3, projection=stereomap)
    stereomap.plot(cmap=reversed_stereo_cmap, title=f"Original STEREO Map\nSTEREO " + \
        str(STEREO_MIN_WAVELENGTH) + "-" + str(STEREO_MAX_WAVELENGTH) + f" {stereomap.date}")
    ax3.set_xlabel(X_LABEL)
    ax3.set_ylabel(Y_LABEL)
    plt.colorbar(fraction=0.046, pad=0.04)

    ax4 = plt.subplot(2, 2, 4, projection=projected_stereomap)
    projected_stereomap.plot(cmap=reversed_stereo_cmap, title="Reprojected to an Earth Observer\nSTEREO " + \
        str(STEREO_MIN_WAVELENGTH) + "-" + str(STEREO_MAX_WAVELENGTH) + f" {projected_stereomap.date}")
    ax4.set_xlabel(X_LABEL)
    ax4.set_ylabel(Y_LABEL)
    plt.colorbar(fraction=0.046, pad=0.04)

    draw_nustar_fov(projected_stereomap, center_x, center_y, layers, rotate=rotate, pixscale=u.Quantity(stereomap.scale).value[0])

    return (ax1,ax2,ax3,ax4)


if __name__ == '__main__':
    reprojection( '2021-11-10T12:00:00', -300, -300, [-100, 0, 100])