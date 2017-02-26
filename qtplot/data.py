import os
import logging
from collections import OrderedDict

import numpy as np
from scipy import ndimage, interpolate, io
from scipy.spatial import qhull
from pandas.io.api import read_table
import pandas as pd

from .util import FixedOrderFormatter, eng_format

logger = logging.getLogger(__name__)


class QtlabFile:
    def __init__(self, filename):
        pass


class QcodesFile:
    def __init__(self, filename):
        pass


class DatFile:
    """ Class which contains the column based DataFrame of the data. """

    def __init__(self, filename):
        self.filename = filename
        self.timestamp = ''

        self.ids = []
        self.labels = []
        self.sizes = {}
        self.shape = ()
        self.ndim = 0

        with open(filename, 'r') as f:
            first_line = f.readline().rstrip('\n\t\r')

            # Test whether the file is generated by qtlab or qcodes
            if first_line.startswith('# Filename: '):
                logger.info('Loading QTLab file %s' % filename)

                self.filename = first_line.split(': ')[1]

                for line in f:
                    line = line.rstrip('\n\t\r')

                    if line.startswith('# Timestamp: '):
                        self.timestamp = line.split(': ', 1)[1]
                    elif line.startswith('#\tname'):
                        name = line.split(': ', 1)[1]

                        self.ids.append(name)
                        self.labels.append(name)
                    elif line.startswith('#\tsize'):
                        size = int(line.split(': ', 1)[1])

                        if size > 1:
                            self.sizes[self.ids[-1]] = size

                        self.shape = self.shape + (size,)

                    # When a line starts with a number we reached the data
                    if len(line) > 0 and line[0] != '#':
                        # Count the number of non length-1 dimensions
                        self.ndim = sum(d > 1 for d in self.shape)
                        break
            else:
                logger.info('Loading QCoDeS file %s' % filename)
                self.ids = first_line.split()[1:]

                column_labels = f.readline().strip()[2:]
                self.labels = [s[1:-1] for s in column_labels.split('\t')]

                column_sizes = f.readline().strip()[2:]
                self.shape = tuple(map(int, column_sizes.split('\t')))

                self.ndim = len(self.shape)

        self.data = read_table(filename, comment='#', sep='\t',
                               header=None).values

        self.load_qtlab_settings(filename)

    def load_qtlab_settings(self, filename):
        self.qtlab_settings = OrderedDict()

        path, ext = os.path.splitext(filename)
        settings_file = path + '.set'
        settings_file_name = os.path.split(settings_file)[1]

        if os.path.exists(settings_file):
            with open(settings_file) as f:
                lines = f.readlines()

            current_instrument = None

            for line in lines:
                line = line.rstrip('\n\t\r')

                if line == '':
                    continue

                if not line.startswith('\t'):
                    name, value = line.split(': ', 1)

                    if (line.startswith('Filename: ') or
                       line.startswith('Timestamp: ')):
                        self.qtlab_settings.update([(name, value)])
                    else:
                        current_instrument = value
                        new = [(current_instrument, OrderedDict())]
                        self.qtlab_settings.update(new)
                else:
                    param, value = line.split(': ', 1)
                    param = param.strip()

                    new = [(param, value)]
                    self.qtlab_settings[current_instrument].update(new)
        else:
            logger.warning('Could not find settings file %s' % settings_file_name)

    def get_column(self, name):
        if name in self.ids:
            return self.data[:, self.ids.index(name)]

    def set_column(self, name, values):
        if name in self.ids:
            self.data[:, self.ids.index(name)] = values
        else:
            self.ids.append(name)
            self.labels.append(name)

            self.data = np.hstack((self.data, values[:, np.newaxis]))

    def get_row_info(self, row):
        # Return a dict of all parameter-value pairs in the row
        return OrderedDict(zip(self.ids, self.data[row]))

    def get_data(self, x_name, y_name, z_name):
        """
        Procedure:
        -   Find columns with size > 1 property, these are the setpoints
        -   Find unique values in the case of two setpoint columns
        -   Pivot into matrix together with selected x, y, and z columns
        -   Transpose to correct form by checking data ranges
        """
        if x_name == '':
            logger.error('You have to select a parameter for the x-axis')

            return None

        if y_name != '' and self.ndim < 2:
            logger.warning('Ignoring the y-axis parameter since it is a 1D dataset')

            y_name = ''

        setpoint_columns = list(self.sizes.keys())

        if len(setpoint_columns) == 0:
            logger.error('No setpoint columns with a size property were found')

            return None
        elif len(setpoint_columns) == 1:
            setpoint_columns.append('')
        elif len(setpoint_columns) > 2:
            logger.warning('Multiple setpoint columns with a size property were found, using the first two')

        # Retrieve the setpoint data, start with 0 for y
        x_setpoints = self.get_column(setpoint_columns[0])
        y_setpoints = np.zeros(self.data.shape[0])

        # The row numbers from the original .dat file
        row_numbers = np.arange(self.data.shape[0])

        # Retrieve the x, y, and z data
        x_data = self.get_column(x_name)
        y_data = np.zeros(self.data.shape[0])
        z_data = self.get_column(z_name)

        # Retrieve y setpoints and data if present
        if len(setpoint_columns) > 1 and y_name != '':
            y_setpoints = self.get_column(setpoint_columns[1])
            y_data = self.get_column(y_name)

        # Find all unique setpoint values
        cols, col_ind = np.unique(x_setpoints, return_inverse=True)
        rows, row_ind = np.unique(y_setpoints, return_inverse=True)

        # Pivot all data into matrix using unique setpoint indices
        pivot = np.zeros((len(rows), len(cols), 6)) * np.nan
        data = np.vstack((x_setpoints, y_setpoints,
                          x_data, y_data, z_data, row_numbers)).T
        pivot[row_ind, col_ind] = data

        x_setpoints = pivot[:,:,0]
        y_setpoints = pivot[:,:,1]

        x = pivot[:,:,2]
        y = pivot[:,:,3]
        z = pivot[:,:,4]

        row_numbers = pivot[:,:,5]

        return Data2D(x, y, z, x_setpoints, y_setpoints, row_numbers,
                      x_name, y_name, z_name, setpoint_columns[0],
                      setpoint_columns[1], self.filename, self.timestamp, self)


def create_kernel(x_dev, y_dev, cutoff, distr):
    distributions = {
        'gaussian': lambda r: np.exp(-(r**2) / 2.0),
        'exponential': lambda r: np.exp(-abs(r) * np.sqrt(2.0)),
        'lorentzian': lambda r: 1.0 / (r**2+1.0),
        'thermal': lambda r: np.exp(r) / (1 * (1+np.exp(r))**2)
    }
    func = distributions[distr]

    hx = np.floor((x_dev * cutoff) / 2.0)
    hy = np.floor((y_dev * cutoff) / 2.0)

    x = np.linspace(-hx, hx, hx * 2 + 1) / x_dev
    y = np.linspace(-hy, hy, hy * 2 + 1) / y_dev

    if x.size == 1: x = np.zeros(1)
    if y.size == 1: y = np.zeros(1)

    xv, yv = np.meshgrid(x, y)

    kernel = func(np.sqrt(xv**2+yv**2))
    kernel /= np.sum(kernel)

    return kernel


class Data2D:
    """
    Class which represents 2d data as two matrices with x and y coordinates
    and one with values.
    """
    def __init__(self, x, y, z, x_setpoints=[], y_setpoints=[], row_numbers=[],
                 x_name='', y_name='', z_name='', x_setpoints_name='',
                 y_setpoints_name='', filename='', timestamp='', dat_file=None,
                 equidistant=(False, False), varying=(False, False)):
        self.x_name, self.y_name, self.z_name = x_name, y_name, z_name
        self.x_setpoints_name = x_setpoints_name
        self.y_setpoints_name = y_setpoints_name
        self.filename, self.timestamp = filename, timestamp
        self.dat_file = dat_file

        # This is not very pretty but I don't see another way.
        # In order to have the datapoint matrices transposed the right way,
        # information about which setpoint belong to which parameter is needed.
        # We don't select this anymore, so we transpose the matrices such that
        # the range of values on a row of the x-coordinate matrix is larger
        # than for a column, which is a reasonable assumption.
        row_range = np.abs(np.nanmax(x, axis=0) - np.nanmin(x, axis=0))
        col_range = np.abs(np.nanmax(x, axis=1) - np.nanmin(x, axis=1))

        if np.average(row_range) > np.average(col_range):
            if x_setpoints is not None and y_setpoints is not None:
                x_setpoints = x_setpoints.T
                y_setpoints = y_setpoints.T

            x = x.T
            y = y.T
            z = z.T

            row_numbers = row_numbers.T

        self.x_setpoints, self.y_setpoints = x_setpoints, y_setpoints
        self.x, self.y, self.z = x, y, z
        self.row_numbers = row_numbers

        self.equidistant = equidistant
        self.varying = varying
        self.tri = None

        # Store column and row averages for linetrace lookup
        self.x_means = np.nanmean(self.x, axis=0)
        self.y_means = np.nanmean(self.y, axis=1)

        if self.varying[0] is True or self.varying[1] is True:
            minx = np.nanmin(x)
            diffx = np.nanmean(np.diff(x, axis=1))
            xrow = minx + np.arange(x.shape[1]) * diffx
            self.x = np.tile(xrow, (x.shape[0], 1))

            miny = np.nanmin(y)
            diffy = np.nanmean(np.diff(y, axis=0))
            yrow = miny + np.arange(y.shape[0]) * diffy
            self.y = np.tile(yrow[:,np.newaxis], (1, y.shape[1]))

    def save(self, filename):
        """
        Save the 2D data to a file.

        format (str): .npy / .mat / .dat
        """
        _, ext = os.path.splitext(filename)

        if ext == '.npy':
            mat = np.dstack((self.x.data, self.y.data, self.z.data))
            np.save(filename, mat)
        elif ext == '.mat':
            mat = np.dstack((self.x.data, self.y.data, self.z.data))
            io.savemat(filename, {'data': mat})
        elif ext == '.dat':
            with open(filename, 'w') as f:
                f.write('# Filename: %s\n' % self.filename)
                f.write('# Timestamp: %s\n' % self.timestamp)
                f.write('\n')

                i = 1

                if len(self.x_setpoints) != 0:
                    f.write('# Column %d\n' % i)
                    f.write('#\tname: %s\n' % self.x_setpoints_name)
                    f.write('#\tsize: %d\n' % self.x_setpoints.shape[1])
                    i += 1

                if len(self.y_setpoints) != 0:
                    f.write('# Column %d\n' % i)
                    f.write('#\tname: %s\n' % self.y_setpoints_name)
                    f.write('#\tsize: %d\n' % self.y_setpoints.shape[1])
                    i += 1

                f.write('# Column %d\n' % i)
                f.write('#\tname: %s\n' % self.x_name)
                i += 1

                f.write('# Column %d\n' % i)
                f.write('#\tname: %s\n' % self.y_name)
                i += 1

                f.write('# Column %d\n' % i)
                f.write('#\tname: %s\n' % self.z_name)

                f.write('\n')

                # Write formatted data
                a = np.vstack((self.x.ravel(), self.y.ravel(), self.z.ravel()))

                if len(self.y_setpoints) != 0:
                    a = np.vstack((self.y_setpoints.ravel(), a))
                if len(self.x_setpoints) != 0:
                    a = np.vstack((self.x_setpoints.ravel(), a))

                df = pd.DataFrame(a.T)
                df.to_csv(f, sep='\t', float_format='%.12e', index=False,
                          header=False)

    def set_data(self, x, y, z):
        self.x, self.y, self.z = x, y, z

    def get_limits(self):
        xmin, xmax = np.nanmin(self.x), np.nanmax(self.x)
        ymin, ymax = np.nanmin(self.y), np.nanmax(self.y)
        zmin, zmax = np.nanmin(self.z), np.nanmax(self.z)

        # Thickness for 1d scans, should we do this here or
        # in the drawing code?
        if xmin == xmax:
            xmin, xmax = -1, 1

        if ymin == ymax:
            ymin, ymax = -1, 1

        return xmin, xmax, ymin, ymax, zmin, zmax

    def get_triangulation_coordinates(self):
        if self.tri is None:
            raise Exception('No triangulation has been generated yet')

        x = self.tri.points[:,0]
        y = self.tri.points[:,1]

        xmin, xmax, ymin, ymax, _, _ = self.get_limits()
        x = x * (xmax - xmin) + xmin
        y = y * (ymax - ymin) + ymin

        return x, y

    def generate_triangulation(self):
        xc = self.x.ravel()
        yc = self.y.ravel()
        zc = self.z.ravel()

        # Remove any NaN values as the triangulation can't handle this
        nans = np.isnan(zc)
        xc = xc[~nans]
        yc = yc[~nans]
        self.no_nan_values = zc[~nans]

        # Normalize the coordinates. This improves the triangulation results
        # in cases where the data ranges on both axes are very different
        # in magnitude
        xmin, xmax, ymin, ymax, _, _ = self.get_limits()
        xc = (xc - xmin) / (xmax - xmin)
        yc = (yc - ymin) / (ymax - ymin)

        self.tri = qhull.Delaunay(np.column_stack((xc, yc)))

    def interpolate(self, points):
        """
        Interpolate points on the 2d data.

        points: N x 2 numpy array with (x, y) as rows
        """
        if self.tri is None:
            self.generate_triangulation()

        xmin, xmax, ymin, ymax, _, _ = self.get_limits()
        points[:,0] = (points[:,0] - xmin) / (xmax - xmin)
        points[:,1] = (points[:,1] - ymin) / (ymax - ymin)

        # Find the indices of the simplices (triangle in this case)
        # to which the points belong to
        simplices = self.tri.find_simplex(points)

        # Find the indices of the datapoints belonging to the simplices
        indices = np.take(self.tri.simplices, simplices, axis=0)
        # Also find the transforms
        transforms = np.take(self.tri.transform, simplices, axis=0)

        # Transform from point coords to barycentric coords
        delta = points - transforms[:,2]
        bary = np.einsum('njk,nk->nj', transforms[:,:2,:], delta)

        temp = np.hstack((bary, 1-bary.sum(axis=1, keepdims=True)))

        values = np.einsum('nj,nj->n', np.take(self.no_nan_values, indices), temp)

        #print values[np.any(temp<0, axis=1)]

        # This should put a NaN for points outside of any simplices
        # but is for some reason sometimes also true inside a simplex
        #values[np.any(temp < 0.0, axis=1)] = np.nan

        return values

    def get_sorted_by_coordinates(self):
        """Return the data sorted so that every coordinate increases."""
        x_indices = np.argsort(self.x[0,:])
        y_indices = np.argsort(self.y[:,0])

        x = self.x[:,x_indices]
        y = self.y[y_indices,:]
        z = self.z[:,x_indices][y_indices,:]

        return x, y, z

    def get_quadrilaterals(self, xc, yc):
        """
        In order to generate quads for every datapoint we do the following
        for the x and y coordinates:
        -   Pad the coordinates with a column/row on each side
        -   Add the difference between all the coords divided by 2 to
            the coords, this generates midpoints
        -   Add a row/column at the end to satisfy the 1 larger
            requirements of pcolor
        """

        # If we are dealing with data that is 2-dimensional
        # -2 rows: both coords need non-nan values
        if xc.shape[1] > 1:
            # Pad both sides with a column of interpolated coordinates
            l0, l1 = xc[:,[0]], xc[:,[1]]
            r1, r0 = xc[:,[-2]], xc[:,[-1]]

            # If there are more than 2 columns/rows, we can extrapolate the
            # datapoint coordinates. Else two columns/rows will not be plotted
            # when plotting an incomplete dataset.
            if xc.shape[1] > 2:
                l2 = xc[:,[2]]
                nans = np.isnan(l0)
                l0[nans] = 2*l1[nans] - l2[nans]
                xc[:,[0]] = l0

                r2 = xc[:,[-3]]
                nans = np.isnan(r0)
                r0[nans] = 2*r1[nans] - r2[nans]
                xc[:,[-1]] = r0

            xc = np.hstack((2*l0 - l1, xc, 2*r0 - r1))
            # Create center points by adding the differences divided by 2 to the original coordinates
            x = xc[:,:-1] + np.diff(xc, axis=1) / 2.0
            # Add a row to the bottom so that the x coords have the same dimension as the y coords
            if np.isnan(x[0]).any():
                x = np.vstack((x, x[-1]))
            else:
                x = np.vstack((x[0], x))
        else:
            # If data is 1d, make one axis range from -.5 to .5
            x = np.hstack((xc - 1, xc[:,[0]] + 1))
            # Duplicate the only row/column so that pcolor has something to actually plot
            x = np.vstack((x, x[0]))

        if yc.shape[0] > 1:
            t0, t1 = yc[0], yc[1]
            b1, b0 = yc[-2], yc[-1]

            if yc.shape[0] > 2:
                t2 = yc[2]
                nans = np.isnan(t0)
                t0[nans] = 2*t1[nans] - t2[nans]
                #yc[0] = t0

                b2 = yc[-3]
                nans = np.isnan(b0)
                b0[nans] = 2*b1[nans] - b2[nans]
                #yc[-1] = b0

            yc = np.vstack([2*t0 - t1, yc, 2*b0 - b1])
            y = yc[:-1,:] + np.diff(yc, axis=0) / 2.0

            if np.isnan(y[:,[0]]).any():
                y = np.hstack([y, y[:,[-1]]])
            else:
                y = np.hstack([y[:,[0]], y])
        else:
            y = np.vstack([yc - 1, yc[0] + 1])
            y = np.hstack([y, y[:,[0]]])

        return x, y

    def get_pcolor(self):
        """
        Return a version of the coordinates and values that can be plotted by pcolor, this means:
        -   Points are sorted by increasing coordinates
        -   Quadrilaterals are generated for every datapoint
        -   NaN values are masked to ignore them when plotting

        Can be plotted using matplotlib's pcolor/pcolormesh(*data.get_pcolor())
        """
        x, y = self.get_quadrilaterals(self.x, self.y)

        return tuple(map(np.ma.masked_invalid, [x, y, self.z]))

    def plot(self, fig, ax, cmap='seismic', font_family='', font_size=12,
             tripcolor=False, show_triangulation=False):
        ax.clear()

        x, y, z = self.get_pcolor()

        if type(cmap) != 'str':
            # It's probably a qtplot Colormap
            cmap = cmap.get_mpl_colormap()

        quadmesh = ax.pcolormesh(x, y, z,
                                      cmap=cmap,
                                      rasterized=True)

        #quadmesh.set_clim(self.main.canvas.colormap.get_limits())

        ax.axis('tight')

        ax.set_title(self.filename)
        ax.set_xlabel(self.x_name)
        ax.set_ylabel(self.y_name)

        ax.xaxis.set_major_formatter(FixedOrderFormatter())
        ax.yaxis.set_major_formatter(FixedOrderFormatter())

        cb = fig.colorbar(quadmesh)

        cb.formatter = FixedOrderFormatter('%.0f', 1)
        cb.update_ticks()
        cb.set_label(self.z_name)
        cb.draw_all()

        fig.tight_layout()

        return cb

    def plot_linetrace(self, fig, ax, type, coordinate,
                       include_coordinate=True, **kwargs):
        ax.clear()

        ax.set_ylabel(self.z_name)

        ax.xaxis.set_major_formatter(FixedOrderFormatter())
        ax.yaxis.set_major_formatter(FixedOrderFormatter())

        if 'color' not in kwargs:
            kwargs['color'] = 'red'
        if 'linewidth' not in kwargs:
            kwargs['linewidth'] = 0.5

        title = '{0}\n{1} = {2}'

        if type == 'horizontal':
            ax.set_xlabel(self.x_name)

            if include_coordinate:
                ax.set_title(title.format(self.filename,
                                          self.y_name,
                                          eng_format(coordinate, 1)))

            x, y, index = self.get_row_at(coordinate)
            z = np.nanmean(self.y[index,:])

            ax.plot(x, y, **kwargs)
        elif type == 'vertical':
            ax.set_xlabel(self.y_name)

            if include_coordinate:
                ax.set_title(title.format(self.filename,
                                          self.x_name,
                                          eng_format(coordinate, 1)))

            x, y, index = self.get_column_at(coordinate)
            z = np.nanmean(self.x[:,index])

            ax.plot(x, y, **kwargs)

        #ax.set_aspect('auto')
        fig.tight_layout()

    def get_column_at(self, x):
        self.x_means = np.nanmean(self.x, axis=0)

        index = np.argmin(np.abs(self.x_means - x))

        return self.y[:,index], self.z[:,index], self.row_numbers[:,index], index

    def get_row_at(self, y):
        self.y_means = np.nanmean(self.y, axis=1)

        index = np.argmin(np.abs(self.y_means - y))

        return self.x[index], self.z[index], self.row_numbers[index], index

    def get_row_index(self, y):
        self.y_means = np.nanmean(self.y, axis=1)

        index = np.argmin(np.abs(self.y_means - y))

        return index

    def get_closest_x(self, x_coord):
        return min(self.x[0,:], key=lambda x:abs(x - x_coord))

    def get_closest_y(self, y_coord):
        return min(self.y[:,0], key=lambda y:abs(y - y_coord))

    def flip_axes(self, x_flip, y_flip):
        if x_flip:
            self.x = np.fliplr(self.x)
            self.y = np.fliplr(self.y)
            self.z = np.fliplr(self.z)
            self.row_numbers = np.fliplr(self.row_numbers)

        if y_flip:
            self.x = np.flipud(self.x)
            self.y = np.flipud(self.y)
            self.z = np.flipud(self.z)
            self.row_numbers = np.flipud(self.row_numbers)

    def is_flipped(self):
        x_flip = self.x[0,0] > self.x[0,-1]
        y_flip = self.y[0,0] > self.y[-1,0]

        return x_flip, y_flip

    def copy(self):
        return Data2D(np.copy(self.x), np.copy(self.y), np.copy(self.z),
                      np.copy(self.x_setpoints), np.copy(self.y_setpoints),
                      np.copy(self.row_numbers),
                      self.x_name, self.y_name, self.z_name,
                      self.x_setpoints_name, self.y_setpoints_name,
                      self.filename, self.timestamp, self.dat_file,
                      self.equidistant, self.varying)

    def abs(self):
        """Take the absolute value of every datapoint."""
        self.z = np.absolute(self.z)

    def autoflip(self):
        """Flip the data so that the X and Y-axes increase to the top and right."""
        self.flip_axes(*self.is_flipped())

    def crop(self, left=0, right=-1, bottom=0, top=-1):
        """Crop a region of the data by the columns and rows."""
        if right < 0:
            right = self.z.shape[1] + right + 1

        if top < 0:
            top = self.z.shape[0] + top + 1

        if (left < right and bottom < top and
            0 <= left <= self.z.shape[1] and 0 <= right <= self.z.shape[1] and
            0 <= bottom <= self.z.shape[0] and 0 <= top <= self.z.shape[0]):
            self.x = self.x[bottom:top,left:right]
            self.y = self.y[bottom:top,left:right]
            self.z = self.z[bottom:top,left:right]
            self.row_numbers = self.row_numbers[bottom:top,left:right]
        else:
            raise ValueError('Invalid crop parameters')

    def dderiv(self, theta=0.0, method='midpoint'):
        """Calculate the component of the gradient in a specific direction."""
        xdir, ydir = np.cos(theta), np.sin(theta)

        xcomp = self.copy()
        xcomp.xderiv(method=method)
        ycomp = self.copy()
        ycomp.yderiv(method=method)

        if method == 'midpoint':
            xvalues = xcomp.z[:-1,:]
            yvalues = ycomp.z[:,:-1]

            self.set_data(xcomp.x[:-1,:], ycomp.y[:,:-1], xvalues * xdir + yvalues * ydir)
        elif method == '2nd order central diff':
            xvalues = xcomp.z[1:-1,:]
            yvalues = ycomp.z[:,1:-1]

            self.set_data(xcomp.x[1:-1,:], ycomp.y[:,1:-1], xvalues * xdir + yvalues * ydir)

    def equalize(self):
        """Perform histogramic equalization on the image."""
        binn = 65535

        # Create a density histogram with surface area 1
        no_nans = self.z[~np.isnan(self.z)]
        hist, bins = np.histogram(no_nans.flatten(), binn)
        cdf = hist.cumsum()

        cdf = bins[0] + (bins[-1]-bins[0]) * (cdf / float(cdf[-1]))

        new = np.interp(self.z.flatten(), bins[:-1], cdf)
        self.z = np.reshape(new, self.z.shape)

    def even_odd(self, even):
        """Extract even or odd rows, optionally flipping odd rows."""
        indices = np.arange(0, self.z.shape[0], 2)

        if not even:
            indices = np.arange(1, self.z.shape[0], 2)

        self.set_data(self.x[indices], self.y[indices], self.z[indices])
        self.row_numbers = self.row_numbers[indices]

    def flip(self, x_flip, y_flip):
        """Flip the X or Y axes."""
        self.flip_axes(x_flip, y_flip)

    def gradmag(self, method='midpoint'):
        """Calculate the length of every gradient vector."""
        xcomp = self.copy()
        xcomp.xderiv(method=method)
        ycomp = self.copy()
        ycomp.yderiv(method=method)

        if method == 'midpoint':
            xvalues = xcomp.z[:-1,:]
            yvalues = ycomp.z[:,:-1]

            self.set_data(xcomp.x[:-1,:], ycomp.y[:,:-1], np.sqrt(xvalues**2 + yvalues**2))
        elif method == '2nd order central diff':
            xvalues = xcomp.z[1:-1,:]
            yvalues = ycomp.z[:,1:-1]

            self.set_data(xcomp.x[1:-1,:], ycomp.y[:,1:-1], np.sqrt(xvalues**2 + yvalues**2))

    def highpass(self, x_width=3, y_height=3, method='gaussian'):
        """Perform a high-pass filter."""
        kernel = create_kernel(x_width, y_height, 7, method)
        self.z = self.z - ndimage.filters.convolve(self.z, kernel)

    def hist2d(self, min, max, bins):
        """Convert every column into a histogram, default bin amount is sqrt(n)."""
        hist = np.apply_along_axis(lambda x: np.histogram(x, bins=bins, range=(min, max))[0], 0, self.z)

        binedges = np.linspace(min, max, bins + 1)
        bincoords = (binedges[:-1] + binedges[1:]) / 2

        self.x = np.tile(self.x[0,:], (hist.shape[0], 1))
        self.y = np.tile(bincoords[:,np.newaxis], (1, hist.shape[1]))
        self.z = hist

    def interp_grid(self, width, height):
        """Interpolate the data onto a uniformly spaced grid using barycentric interpolation."""
        # NOT WOKRING FOR SOME REASON
        xmin, xmax, ymin, ymax, _, _ = self.get_limits()

        x = np.linspace(xmin, xmax, width)
        y = np.linspace(ymin, ymax, height)
        xv, yv = np.meshgrid(x, y)

        self.x, self.y = xv, yv
        self.z = np.reshape(self.interpolate(np.column_stack((xv.flatten(), yv.flatten()))), xv.shape)

    def interp_x(self, points):
        """Interpolate every row onto a uniformly spaced grid."""
        xmin, xmax, ymin, ymax, _, _ = self.get_limits()

        x = np.linspace(xmin, xmax, points)

        rows = self.z.shape[0]
        values = np.zeros((rows, points))

        for i in range(rows):
            f = interpolate.interp1d(self.x[i], self.z[i],
                                     bounds_error=False, fill_value=np.nan)
            values[i] = f(x)

        y_avg = np.average(self.y, axis=1)[np.newaxis].T

        self.set_data(np.tile(x, (rows,1)), np.tile(y_avg, (1, points)), values)

    def interp_y(self, points):
        """Interpolate every column onto a uniformly spaced grid."""
        xmin, xmax, ymin, ymax, _, _ = self.get_limits()

        y = np.linspace(ymin, ymax, points)[np.newaxis].T

        cols = self.z.shape[1]
        values = np.zeros((points, cols))

        for i in range(cols):
            f = interpolate.interp1d(self.y[:,i].ravel(), self.z[:,i].ravel(),
                                     bounds_error=False, fill_value=np.nan)
            values[:,i] = f(y).ravel()

        x_avg = np.average(self.x, axis=0)

        self.set_data(np.tile(x_avg, (points,1)), np.tile(y, (1,cols)), values)

    def log(self, subtract, min):
        """The base-10 logarithm of every datapoint."""
        minimum = np.nanmin(self.z)

        if subtract:
            #self.z[self.z < 0] = newmin
            self.z += (min - minimum)

        self.z = np.log10(self.z)

    def lowpass(self, x_width=3, y_height=3, method='gaussian'):
        """Perform a low-pass filter."""
        kernel = create_kernel(x_width, y_height, 7, method)
        self.z = ndimage.filters.convolve(self.z, kernel)

        self.z = np.ma.masked_invalid(self.z)

    def negate(self):
        """Negate every datapoint."""
        self.z *= -1

    def norm_columns(self):
        """Transform the values of every column so that they use the full colormap."""
        def func(x):
            return (x - np.nanmin(x)) / (np.nanmax(x) - np.nanmin(x))

        self.z = np.apply_along_axis(func, 0, self.z)

    def norm_rows(self):
        """Transform the values of every row so that they use the full colormap."""
        def func(x):
            return (x - np.nanmin(x)) / (np.nanmax(x) - np.nanmin(x))

        self.z = np.apply_along_axis(func, 1, self.z)

    def offset(self, offset=0):
        """Add a value to every datapoint."""
        self.z += offset

    def offset_axes(self, x_offset=0, y_offset=0):
        """Add an offset value to the axes."""
        self.x += x_offset
        self.y += y_offset

    def power(self, power=1):
        """Raise the datapoints to a power."""
        self.z = np.power(self.z, power)

    def scale_axes(self, x_scale=1, y_scale=1):
        """Multiply the axes values by a number."""
        self.x *= x_scale
        self.y *= y_scale

    def scale_data(self, factor):
        """Multiply the datapoints by a number."""
        self.z *= factor

    def sub_linecut(self, type, position):
        """Subtract a horizontal/vertical linecut from every row/column."""
        if type == 'horizontal':
            x, y, row_numbers, index = self.get_row_at(position)
            y = np.tile(self.z[index,:], (self.z.shape[0],1))
        elif type == 'vertical':
            x, y, row_numbers, index = self.get_column_at(position)
            y = np.tile(self.z[:,index][:,np.newaxis], (1, self.z.shape[1]))

        self.z -= y

    def sub_linecut_avg(self, type, position, size):
        """Subtract a horizontal/vertical averaged linecut from every row/column."""
        if size % 2 == 0:
            start, end = -size/2, size/2-1
        else:
            start, end = -(size-1)/2, (size-1)/2

        indices = np.arange(start, end + 1)

        if type == 'horizontal':
            x, y, index = self.get_row_at(position)
            y = np.mean(self.z[index+indices,:], axis=0)
            y = np.tile(y, (self.z.shape[0],1))
        elif type == 'vertical':
            x, y, index = self.get_column_at(position)
            y = np.mean(self.z[:,index+indices][:,np.newaxis], axis=1)
            y = np.tile(y, (1, self.z.shape[1]))

        self.z -= y

    def sub_plane(self, x_slope, y_slope):
        """Subtract a plane with x and y slopes centered in the middle."""
        xmin, xmax, ymin, ymax, _, _ = self.get_limits()

        self.z -= x_slope*(self.x - (xmax - xmin)/2) + y_slope*(self.y - (ymax - ymin)/2)

    def xderiv(self, method='midpoint'):
        """Find the rate of change between every datapoint in the x-direction."""
        if method == 'midpoint':
            dx = np.diff(self.x, axis=1)
            ddata = np.diff(self.z, axis=1)

            self.x = self.x[:,:-1] + dx / 2.0
            self.y = self.y[:,:-1]
            self.z = ddata / dx
        elif method == '2nd order central diff':
            self.z = (self.z[:,2:] - self.z[:,:-2]) / (self.x[:,2:] - self.x[:,:-2])
            self.x = self.x[:,1:-1]
            self.y = self.y[:,1:-1]

    def yderiv(self, method='midpoint'):
        """Find the rate of change between every datapoint in the y-direction."""
        if method == 'midpoint':
            dy = np.diff(self.y, axis=0)
            ddata = np.diff(self.z, axis=0)

            self.x = self.x[:-1,:]
            self.y = self.y[:-1,:] + dy / 2.0
            self.z = ddata / dy
        elif method == '2nd order central diff':
            self.z = (self.z[2:] - self.z[:-2]) / (self.y[2:] - self.y[:-2])
            self.x = self.x[1:-1]
            self.y = self.y[1:-1]
