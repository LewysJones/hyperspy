import math
import numbers

import numpy as np
import matplotlib.pyplot as plt
from scipy import constants

from hyperspy.misc.array_tools import rebin
from hyperspy.misc.utils import unfold_if_multidim
from hyperspy.gui import messages as messagesui
import hyperspy.defaults_parser


def _estimate_gain(ns, cs,
                   weighted=False,
                   higher_than=None,
                   plot_results=False,
                   binning=0,
                   pol_order=1):
    if binning > 0:
        factor = 2 ** binning
        remainder = np.mod(ns.shape[1], factor)
        if remainder != 0:
            ns = ns[:,remainder:]
            cs = cs[:,remainder:]
        new_shape = (ns.shape[0], ns.shape[1]/factor)
        ns = rebin(ns, new_shape)
        cs = rebin(cs, new_shape)

    noise = ns - cs
    variance = np.var(noise, 0)
    average = np.mean(cs, 0).squeeze()

    # Select only the values higher_than for the calculation
    if higher_than is not None:
        sorting_index_array = np.argsort(average)
        average_sorted = average[sorting_index_array]
        average_higher_than = average_sorted > higher_than
        variance_sorted = variance.squeeze()[sorting_index_array]
        variance2fit = variance_sorted[average_higher_than]
        average2fit = average_sorted[average_higher_than]
    else:
        variance2fit = variance
        average2fit = average

    fit = np.polyfit(average2fit, variance2fit, pol_order)
    if weighted is True:
        from hyperspy._signals.spectrum import Spectrum
        from hyperspy.model import Model
        from hyperspy.components import Line
        s = Spectrum(variance2fit)
        s.axes_manager.signal_axes[0].axis = average2fit
        m = Model(s)
        l = Line()
        l.a.value = fit[1]
        l.b.value = fit[0]
        m.append(l)
        m.fit(weights=True)
        fit[0] = l.b.value
        fit[1] = l.a.value

    if plot_results is True:
        plt.figure()
        plt.scatter(average.squeeze(), variance.squeeze())
        plt.xlabel('Counts')
        plt.ylabel('Variance')
        plt.plot(average2fit, np.polyval(fit,average2fit), color = 'red')
    results = {'fit' : fit, 'variance' : variance.squeeze(),
    'counts' : average.squeeze()}

    return results

def _estimate_correlation_factor(g0, gk,k):
    a = math.sqrt(g0/gk)
    e = k*(a-1)/(a-k)
    c = (1 - e)**2
    return c

def estimate_variance_parameters(
    noisy_signal,
    clean_signal,
    mask=None,
    pol_order=1,
    higher_than=None,
    return_results=False,
    plot_results=True,
    weighted=False):
    """Find the scale and offset of the Poissonian noise

    By comparing an SI with its denoised version (i.e. by PCA),
    this plots an
    estimation of the variance as a function of the number of counts
    and fits a
    polynomy to the result.

    Parameters
    ----------
    noisy_SI, clean_SI : spectrum.Spectrum instances
    mask : numpy bool array
        To define the channels that will be used in the calculation.
    pol_order : int
        The order of the polynomy.
    higher_than: float
        To restrict the fit to counts over the given value.

    return_results : Bool

    plot_results : Bool

    Returns
    -------
    Dictionary with the result of a linear fit to estimate the offset
    and scale factor

    """
    fold_back_noisy =  unfold_if_multidim(noisy_signal)
    fold_back_clean =  unfold_if_multidim(clean_signal)

    # The rest of the code assumes that the first data axis
    # is the navigation axis. We transpose the data if that is not the
    # case.
    ns = (noisy_signal.data.copy()
          if noisy_signal.axes_manager[0].index_in_array == 0
          else noisy_signal.data.T.copy())
    cs = (clean_signal.data.copy()
          if clean_signal.axes_manager[0].index_in_array == 0
          else clean_signal.data.T.copy())

    if mask is not None:
        _slice = [slice(None),] * len(ns.shape)
        _slice[noisy_signal.axes_manager.signal_axes[0].index_in_array]\
         = ~mask
        ns = ns[_slice]
        cs = cs[_slice]

    results0 = _estimate_gain(ns, cs, weighted=weighted,
        higher_than=higher_than, plot_results=plot_results, binning=0,
        pol_order=pol_order)

    results2 = _estimate_gain(ns, cs, weighted=weighted,
        higher_than=higher_than, plot_results=False, binning=2,
        pol_order=pol_order)

    c = _estimate_correlation_factor(results0['fit'][0],
                                     results2['fit'][0], 4)

    message = ("Gain factor: %.2f\n" % results0['fit'][0] +
               "Gain offset: %.2f\n" % results0['fit'][1] +
               "Correlation factor: %.2f\n" % c )
    is_ok = True
    if hyperspy.defaults_parser.preferences.General.interactive is True:
        is_ok = messagesui.information(
            message + "Would you like to store the results?")
    else:
        print message
    if is_ok:
        if not noisy_signal.mapped_parameters.has_item(
            'Variance_estimation'):
            noisy_signal.mapped_parameters.add_node(
                'Variance_estimation')
        noisy_signal.mapped_parameters.Variance_estimation.gain_factor = \
            results0['fit'][0]
        noisy_signal.mapped_parameters.Variance_estimation.gain_offset = \
            results0['fit'][1]
        noisy_signal.mapped_parameters.Variance_estimation.correlation_factor = c
        noisy_signal.mapped_parameters.Variance_estimation.\
        parameters_estimation_method = 'Hyperspy'

    if fold_back_noisy is True:
        noisy_signal.fold()
    if fold_back_clean is True:
        clean_signal.fold()

    if return_results is True:
        return results0

def power_law_perc_area(E1,E2, r):
    a = E1
    b = E2
    return 100*((a**r*r-a**r)*(a/(a**r*r-a**r)-(b+a)/((b+a)**r*r-(b+a)**r)))/a

def rel_std_of_fraction(a, std_a, b, std_b, corr_factor=1):
    rel_a = std_a/a
    rel_b = std_b/b
    return np.sqrt(rel_a**2 + rel_b**2 -
                   2 * rel_a * rel_b * corr_factor)

def ratio(edge_A, edge_B):
    a = edge_A.intensity.value
    std_a = edge_A.intensity.std
    b = edge_B.intensity.value
    std_b = edge_B.intensity.std
    ratio = a/b
    ratio_std = ratio * rel_std_of_fraction(a, std_a,b, std_b)
    print "Ratio %s/%s %1.3f +- %1.3f " % (
        edge_A.name,
        edge_B.name,
        a/b,
        1.96*ratio_std)
    return ratio, ratio_std

def eels_constant(s, zlp, t):
    """Calculate the constant of proportionality (k) in the relationship
    between the EELS signal and the dielectric function.
    dielectric function from a single scattering distribution (SSD) using
    the Kramers-Kronig relations.

    $S(E)=\frac{I_{0}t}{\pi a_{0}m_{0}v^{2}}\ln\left[1+\left(\frac{\beta}
    {\theta_{E}}\right)^{2}\right]\Im(\frac{-1}{\epsilon(E)})=
    k\Im(\frac{-1}{\epsilon(E)})$


    Parameters
    ----------
    zlp: {number, Signal}
        If the ZLP is the same for all spectra, the intengral of the ZLP
        can be provided as a number. Otherwise, if the ZLP intensity is not
        the same for all spectra, it can be provided as i) a Signal
        of the same dimensions as the current signal containing the ZLP
        spectra for each location ii) a Signal of signal dimension 0
        and navigation_dimension equal to the current signal containing the
        integrated ZLP intensity.
    t: {None, number, Signal}
        The sample thickness in nm. If the thickness is the same for all
        spectra it can be given by a number. Otherwise, it can be provided
        as a Signal with signal dimension 0 and navigation_dimension equal
        to the current signal.

    Returns
    -------
    k: Signal instance

    """

    # Constants and units
    me = constants.value(
        'electron mass energy equivalent in MeV') * 1e3 # keV

    # Mapped parameters
    try:
        e0 = s.mapped_parameters.TEM.beam_energy
    except:
        raise AttributeError("Please define the beam energy."
                                "You can do this e.g. by using the "
                                "set_microscope_parameters method")
    try:
        beta = s.mapped_parameters.TEM.EELS.collection_angle
    except:
        raise AttributeError("Please define the collection angle."
                                "You can do this e.g. by using the "
                                "set_microscope_parameters method")

    axis = s.axes_manager.signal_axes[0]
    eaxis = axis.axis.copy()
    if eaxis[0] == 0:
        # Avoid singularity at E=0
        eaxis[0] = 1e-10

    if isinstance(zlp, hyperspy.signal.Signal):
        if (zlp.axes_manager.navigation_dimension ==
            s.axes_manager.navigation_dimension):
            if zlp.axes_manager.signal_dimension == 0:
                i0 = i0.data
            else:
                i0 = zlp.data.sum(axis.index_in_array)
        else:
            raise ValueError('The ZLP signal dimensions are not '
                                'compatible with the dimensions of the '
                                'low-loss signal')
        i0 = i0.reshape(
                np.insert(i0.shape, axis.index_in_array, 1))
    elif isinstance(zlp, numbers.Number):
        i0 = zlp
    else:
        raise ValueError('The zero-loss peak input is not valid.')

    if isinstance(t, hyperspy.signal.Signal):
        if (t.axes_manager.navigation_dimension ==
            s.axes_manager.navigation_dimension) and (
            t.axes_manager.signal_dimension == 0):
                t = t.data
                t = t.reshape(
                        np.insert(t.shape, axis.index_in_array, 1))
        else:
            raise ValueError('The thickness signal dimensions are not '
                                'compatible with the dimensions of the '
                                'low-loss signal')
    # Slicer to get the signal data from 0 to axis.size
    slicer = s.axes_manager._get_data_slice(
            [(axis.index_in_array, slice(None,axis.size)),])

    # Kinetic definitions
    ke = e0 * (1 + e0 / 2. / me) / (1 + e0 / me) ** 2
    tgt = e0 * (2 * me + e0) / (me + e0)
    k = s._get_navigation_signal()
    k.data = (t * i0 / (332.5 * ke)) * np.log(1 + (beta * tgt / eaxis) ** 2)
    k.mapped_parameters.title = "EELS proportionality constant K"
    return k