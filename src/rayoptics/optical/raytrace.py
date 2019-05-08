#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright © 2018 Michael J. Hayford
""" Functions to support ray tracing a sequential optical model

.. Created on Thu Jan 25 11:01:04 2018

.. codeauthor: Michael J. Hayford
"""

import itertools
import numpy as np
from numpy.linalg import norm
from math import sqrt, copysign

import rayoptics.optical.model_constants as mc
from .traceerror import TraceMissedSurfaceError, TraceTIRError


Intfc, Gap, Index, Trfm, Z_Dir = range(5)
#pt, dcs = range(2)


def bend(d_in, normal, n_in, n_out):
    """ refract incoming direction, d_in, about normal """
    try:
        normal_len = norm(normal)
        cosI = np.dot(d_in, normal)/normal_len
        sinI_sqr = 1.0 - cosI*cosI
        n_cosIp = copysign(sqrt(n_out*n_out - n_in*n_in*sinI_sqr), cosI)
        alpha = n_cosIp - n_in*cosI
        d_out = (n_in*d_in + alpha*normal)/n_out
        return d_out
    except ValueError:
        raise TraceTIRError(d_in, normal, n_in, n_out)


def reflect(d_in, normal):
    """ reflect incoming direction, d_in, about normal """
    normal_len = norm(normal)
    cosI = np.dot(d_in, normal)/normal_len
    d_out = d_in - 2.0*cosI*normal
    return d_out


def phase(intrfc, inc_pt, d_in, normal, wvl, n_in, n_out):
    """ apply phase shift to incoming direction, d_in, about normal """
    d_out, dW = intrfc.phase(inc_pt, d_in, normal, wvl)
    return d_out, dW


def trace(seq_model, pt0, dir0, wvl, **kwargs):
    """ fundamental raytrace function

    Args:
        seq_model: the sequential model to be traced
        pt0: starting point in coords of first interface
        dir0: starting direction cosines in coords of first interface
        wvl: wavelength in nm
        eps: accuracy tolerance for surface intersection calculation

    Returns:
        (**ray**, **op_delta**, **wvl**)

        - **ray** is a list for each interface in **path_pkg** of these
          elements: [pt, after_dir, after_dst, normal]

            - pt: the intersection point of the ray
            - after_dir: the ray direction cosine following the interface
            - after_dst: after_dst: the geometric distance to the next
              interface
            - normal: the surface normal at the intersection point

        - **op_delta** - optical path wrt equally inclined chords to the
          optical axis
        - **wvl** - wavelength (in nm) that the ray was traced in
    """
    path = itertools.zip_longest(seq_model.ifcs, seq_model.gaps,
                                 seq_model.rndx[wvl], seq_model.lcl_tfrms,
                                 seq_model.z_dir)
    path_pkg = (path, seq_model.get_num_surfaces())
    return trace_raw(path_pkg, pt0, dir0, wvl, **kwargs)


def trace_raw(path_pkg, pt0, dir0, wvl, eps=1.0e-12):
    """ fundamental raytrace function

    Args:
        path_pkg: an iterator containing interfaces and gaps to be traced
        pt0: starting point in coords of first interface
        dir0: starting direction cosines in coords of first interface
        wvl: wavelength in nm
        eps: accuracy tolerance for surface intersection calculation

    Returns:
        (**ray**, **op_delta**, **wvl**)

        - **ray** is a list for each interface in **path_pkg** of these
          elements: [pt, after_dir, after_dst, normal]

            - pt: the intersection point of the ray
            - after_dir: the ray direction cosine following the interface
            - after_dst: after_dst: the geometric distance to the next
              interface
            - normal: the surface normal at the intersection point

        - **op_delta** - optical path wrt equally inclined chords to the
          optical axis
        - **wvl** - wavelength (in nm) that the ray was traced in
    """
    ray = []
    eic = []

    path, path_length = path_pkg

    # trace object surface
    obj = next(path)
    srf_obj = obj[Intfc]
    dst_b4, pt_obj = srf_obj.intersect(pt0, dir0)

    before = obj
    before_pt = pt_obj
    before_dir = dir0
    before_normal = srf_obj.normal(before_pt)
    tfrm_from_before = before[Trfm]
    z_dir_before = before[Z_Dir]
    n_before = before[Index] if z_dir_before > 0.0 else -before[Index]

    op_delta = 0.0
    surf = 0
    # loop of remaining surfaces in path
    while True:
        try:
            after = next(path)

            rt, t = tfrm_from_before
            b4_pt, b4_dir = rt.dot(before_pt - t), rt.dot(before_dir)

            pp_dst = -b4_pt.dot(b4_dir)
            pp_pt_before = b4_pt + pp_dst*b4_dir

            ifc = after[Intfc]
            z_dir_after = after[Z_Dir]
            n_after = after[Index] if z_dir_after > 0.0 else -after[Index]

            # intersect ray with profile
            pp_dst_intrsct, inc_pt = ifc.intersect(pp_pt_before, b4_dir,
                                                   eps=eps, z_dir=z_dir_before)
            dst_b4 = pp_dst + pp_dst_intrsct
            ray.append([before_pt, before_dir, dst_b4, before_normal])

            normal = ifc.normal(inc_pt)

            eic_dst_before = ((inc_pt.dot(b4_dir) + z_dir_before*inc_pt[2]) /
                              (1.0 + z_dir_before*b4_dir[2]))

            # refract or reflect ray at interface
            if ifc.refract_mode == 'REFL':
                after_dir = reflect(b4_dir, normal)
            elif ifc.refract_mode == 'PHASE':
                after_dir, phs = phase(ifc, inc_pt, b4_dir, normal, wvl,
                                       n_before, n_after)
                op_delta += phs
            else:
                after_dir = bend(b4_dir, normal, n_before, n_after)

            eic_dst_after = ((inc_pt.dot(after_dir) + z_dir_after*inc_pt[2]) /
                             (1.0 + z_dir_after*after_dir[2]))

            surf += 1

            dW = n_after*eic_dst_after - n_before*eic_dst_before
            eic.append([n_before, eic_dst_before,
                        n_after, eic_dst_after, dW])

#            print("after:", surf, inc_pt, after_dir)
#            print("e{}= {:12.5g} e{}'= {:12.5g} dW={:10.8g} n={:8.5g}"
#                  " n'={:8.5g}".format(surf, eic_dst_before,
#                                       surf, eic_dst_after,
#                                       dW, before[Index], after[Index]))
            before_pt = inc_pt
            before_normal = normal
            before_dir = after_dir
            n_before = n_after
            z_dir_before = z_dir_after
            before = after
            tfrm_from_before = before[Trfm]

        except TraceMissedSurfaceError as ray_miss:
            ray.append([before_pt, before_dir, pp_dst, before_normal])
            ray_miss.surf = surf+1
            ray_miss.ifc = ifc
            ray_miss.prev_gap = after[Gap]
            ray_miss.ray = ray
            raise ray_miss

        except TraceTIRError as ray_tir:
            ray.append([inc_pt, before_dir, 0.0, normal])
            ray_tir.surf = surf+1
            ray_tir.ifc = ifc
            ray_tir.inc_pt = inc_pt
            ray_tir.ray = ray
            raise ray_tir

        except StopIteration:
            ray.append([inc_pt, after_dir, 0.0, normal])
            if len(eic) > 1:
                P, P1k, Ps = calc_path_length(eic, offset=1)
                op_delta += P
            break

    return ray, op_delta, wvl


def calc_path_length(eic, offset=0):
    """ given eic array, compute path length between outer surfaces

    Args:
        eic: equally inclined chord array
        offset (int): beginning index of eic array wrt the object interface

    Returns:
        double: path length
    """
    P1k = -eic[1-offset][2]*eic[1-offset][3] + eic[-2][0]*eic[-2][1]
    Ps = 0.
    for i in range(2-offset, len(eic)-2):
        Ps -= eic[i][4]
#        Ps -= eic[i][2]*eic[i][3] - eic[i][0]*eic[i][1]
    P = P1k + Ps
    return P, P1k, Ps


def eic_distance(r, r0):
    """ calculate equally inclined chord distance between 2 rays

    Args:
        r: (p, d), where p is a point on the ray r and d is the direction
           cosine of r
        r0: (p0, d0), where p0 is a point on the ray r0 and d0 is the direction
            cosine of r0

    Returns:
        double: distance along r from equally inclined chord point to p
    """
    # eq 3.9
    e = (np.dot(r[1] + r0[1], r[0] - r0[0]) / (1. + np.dot(r[1], r0[1])))
    return e


def wave_abr(fld, wvl, ray_pkg):
    return wave_abr_real_coord(fld, wvl, ray_pkg)
#    return wave_abr_HHH(fld.ref_sphere_pkg, fld.chief_ray_pkg, ray_pkg)


def wave_abr_real_coord(fld, wvl, ray_pkg):
    ref_sphere, parax_data, n_obj, n_img, z_dir = fld.ref_sphere
    image_pt, cr_exp_pt, cr_exp_dist, ref_dir, ref_sphere_radius = ref_sphere
    chief_ray, chief_ray_op, wvl = fld.chief_ray[0]
    ray, ray_op, wvl = ray_pkg
    fod = parax_data[2]
    k = -2  # last interface in sequence

    # eq 3.12
    e1 = eic_distance((ray[1][mc.p], ray[0][mc.d]),
                      (chief_ray[1][mc.p], chief_ray[0][mc.d]))
    # eq 3.13
    ekp = eic_distance((ray[k][mc.p], ray[k][mc.d]),
                       (chief_ray[k][mc.p], chief_ray[k][mc.d]))

    dst = ekp - cr_exp_dist

    eic_exp_pt = ray[k][mc.p] - dst*ray[k][mc.d]
#    eic_exp_pt[2] -= cr_exp_dist
    p_coord = eic_exp_pt - cr_exp_pt
    F = ref_dir.dot(ray[k][mc.d]) - ray[k][mc.d].dot(p_coord)/ref_sphere_radius
    J = p_coord.dot(p_coord)/ref_sphere_radius - 2.0*ref_dir.dot(p_coord)
    ep = J/(F + sqrt(F**2 + J/ref_sphere_radius))

    opd = -n_obj*e1 - ray_op + n_img*ekp + chief_ray_op - n_img*ep
    return opd, e1, ekp, ep


def wave_abr_HHH(fld, wvl, ray_pkg):
    ref_sphere, parax_data, n_obj, n_img, z_dir = fld.ref_sphere
    image_pt, cr_exp_pt, ref_dir, ref_sphere_radius = ref_sphere
    chief_ray, chief_ray_op, wvl = fld.chief_ray
    ray, ray_op, wvl = ray_pkg
    ax_ray, pr_ray, fod = parax_data
    k = -2  # last interface in sequential model
    ax_k = ax_ray[k]
    pr_k = pr_ray[k]
    ht, slp = range(2)
    H = n_img*(pr_k[ht]*ax_k[slp] - ax_k[ht]*pr_k[slp])

    # eq 3.12
    e1 = eic_distance((ray[1][mc.p], ray[0][mc.d]),
                      (chief_ray[1][mc.p], chief_ray[0][mc.d]))
    # eq 3.13
    ekp = eic_distance((ray[k][mc.p], ray[k][mc.d]),
                       (chief_ray[k][mc.p], chief_ray[k][mc.d]))

    # eq 4.33
    eic_pt = ray[k][mc.p] - ekp*ray[k][mc.d]
    print("eic_pt", eic_pt)

    Nk_cr = chief_ray[k][mc.d][2]
    Zk_cr = chief_ray[k][mc.p][2]

    def reduced_pupil_coord(X, L, e):
        coef1 = -n_img/(H * Nk_cr)
        xp = coef1*(pr_k[slp]*(Nk_cr*(X - L*e) - L*Zk_cr) +
                    pr_k[ht]*L)
        return xp

    # eq 5.4
    xp_ray = reduced_pupil_coord(ray[k][mc.p][0], ray[k][mc.d][0], ekp)
    yp_ray = reduced_pupil_coord(ray[k][mc.p][1], ray[k][mc.d][1], ekp)
    # eq 5.5
    xp_cr = reduced_pupil_coord(chief_ray[k][mc.p][0], chief_ray[k][mc.d][0], 0.)
    yp_cr = reduced_pupil_coord(chief_ray[k][mc.p][1], chief_ray[k][mc.d][1], 0.)
    # eq 5.6
    zp_ray = -(((ray[k][mc.d][0] + chief_ray[k][mc.d][0])*(xp_ray - xp_cr) +
                (ray[k][mc.d][1] + chief_ray[k][mc.d][1])*(yp_ray - yp_cr)) /
                (ray[k][mc.d][2] + chief_ray[k][mc.d][2]))

    rpc_ray = np.array([xp_ray, yp_ray, zp_ray])
    rpc_cr = np.array([xp_cr, yp_cr, 0.])
    print("rpc ray", xp_ray, yp_ray, zp_ray)
    print("rpc cr", xp_cr, yp_cr, 0.)
    # eq 4.11
    G0_ref = n_img*ax_k[slp]*image_pt[0]
    H0_ref = n_img*ax_k[slp]*image_pt[1]

    def reduced_image_coord(X, L, Z, N):
        G0 = (n_img/N)*(ax_k[slp]*(N*X - L*Z) + ax_k[ht]*L)
        return G0

    # eq 5.13
    G0_ray = reduced_image_coord(ray[k][mc.p][0], ray[k][mc.d][0],
                                 ray[k][mc.p][2], ray[k][mc.d][2])
    H0_ray = reduced_image_coord(ray[k][mc.p][1], ray[k][mc.d][1],
                                 ray[k][mc.p][2], ray[k][mc.d][2])
    # eq 5.14
    G0_cr = reduced_image_coord(chief_ray[k][mc.p][0], chief_ray[k][mc.d][0],
                                Zk_cr, Nk_cr)
    H0_cr = reduced_image_coord(chief_ray[k][mc.p][1], chief_ray[k][mc.d][1],
                                Zk_cr, Nk_cr)
    print("G0, H0_ref; G0, H0_cr:", G0_ref, H0_ref, G0_cr, H0_cr)
    # eq 4.17
    a = pr_k[slp]*G0_ref/H + ax_k[slp]*xp_cr
    b = pr_k[slp]*H0_ref/H + ax_k[slp]*yp_cr
    g = z_dir/sqrt(1. - a**2 + b**2)
    # eq 4.18
    ref_dir = np.array([-a*g, -b*g, g])
    print("ref_dir, cr_dir", ref_dir, chief_ray[k][mc.d])
    # eq 4.25
    F = (np.dot(ref_dir, ray[k][mc.d]) + ref_dir[2]*ax_k[slp] *
         np.dot(chief_ray[k][mc.d], (rpc_ray - rpc_cr)))

    # eq 4.28
    Ja = (ref_dir[2]*ax_k[slp] *
          np.dot((eic_pt - chief_ray[k][0]), (rpc_ray - rpc_cr)))
    Jb = -(2.0*(ref_dir[2]/Nk_cr)*(ax_k[ht] - ax_k[slp]*Zk_cr) *
           np.dot(chief_ray[k][mc.d], (rpc_ray - rpc_cr)))
    Jc = (2.0*(ref_dir[2]/n_img)*((G0_cr - G0_ref)*(xp_ray - xp_cr) +
                                  (H0_cr - H0_ref)*(yp_ray - yp_cr)))
    J = Ja + Jb + Jc
    print("F, J, Ja, Jb, Jc", F, J, Ja, Jb, Jc)
#    J = ((ref_dir[2]*ax_k[slp] *
#         np.dot((eic_pt - chief_ray[k][0]), (rpc_ray - rpc_cr))) -
#         2.0*(ref_dir[2]/Nk_cr)*(ax_k[ht] - ax_k[slp]*Zk_cr) *
#         np.dot(chief_ray[k][mc.d], (rpc_ray - rpc_cr)) +
#         2.0*(ref_dir[2]/n_img)*((G0_cr - G0_ref)*(xp_ray - xp_cr) +
#                                 (H0_cr - H0_ref)*(yp_ray - yp_cr)))

#    # eq 4.29 Q' = image_pt
#    F = (np.dot(chief_ray[k][mc.d], ray[k][mc.d]) + Nk_cr*ax_k[slp] *
#         np.dot(chief_ray[k][mc.d], (rpc_ray - rpc_cr)))
#    J = ((Nk_cr*ax_k[slp] *
#         np.dot((eic_pt - chief_ray[k][0]), (rpc_ray - rpc_cr))) -
#         2.0*(ax_k[ht] - ax_k[slp]*Zk_cr) *
#         np.dot(chief_ray[k][mc.d], (rpc_ray - rpc_cr)))

    # eq 4.21
    ep = J/(F + sqrt(F**2 + J*(n_img*ax_k[slp]*pr_k[slp]*ref_dir[2] / H)))

    print("F, J, ep (canon)", F, J, ep)

    # eq 3.14/3.22, using 3.15
    opd = -n_obj*e1 - ray_op + n_img*ekp + chief_ray_op - n_img*ep
    return opd, e1, ekp, ep


def transfer_to_exit_pupil(interface, ray_seg, exp_dst_parax):
    if interface.decenter:
        # get transformation info after surf
        r, t = interface.decenter.tform_after_surf()
        rt = r.transpose()
        b4_pt, b4_dir = rt.dot(ray_seg[0] - t), rt.dot(ray_seg[1])
    else:
        b4_pt, b4_dir = ray_seg[0], ray_seg[1]

    h = b4_pt[0]**2 + b4_pt[1]**2
    u = b4_dir[0]**2 + b4_dir[1]**2
    if u == 0.0:
        dst = exp_dst_parax
    else:
        dst = -sqrt(h/u)

    exp_pt = b4_pt + dst*b4_dir

    return exp_pt, b4_dir, dst


def eic_path_accumulation(ray, rndx, lcl_tfrms, z_dir):
    """ computes equally inclined chords and path info for ray

    Args:
        ray: ray data for traced ray
        rndx: refractive index array
        lcl_tfrms: local surface interface transformation data
        z_dir: z direction array

    Returns:
        (**eic**, **op_delta**)

        - **eic** - list of [n_before, eic_dst_before, n_after, eic_dst_after,
          dW]
        - **op_delta** - optical path wrt equally inclined chords to the
          optical axis
    """
    eic = []

    z_dir_before = z_dir[0]
    n_before = z_dir_before*rndx[0]

    before_dir = ray[0][1]

    for i, r in enumerate(ray):
        rotT, _ = lcl_tfrms[i]
        b4_dir = rotT.dot(before_dir)

        z_dir_after = z_dir[i]
        n_after = z_dir_after*rndx[i]

        inc_pt = ray[i][0]
        eic_dst_before = ((inc_pt.dot(b4_dir) + z_dir_before*inc_pt[2]) /
                          (1.0 + z_dir_before*b4_dir[2]))

        after_dir = ray[i][1]
        eic_dst_after = ((inc_pt.dot(after_dir) + z_dir_after*inc_pt[2]) /
                         (1.0 + z_dir_after*after_dir[2]))

        dW = n_after*eic_dst_after - n_before*eic_dst_before

        eic.append([n_before, eic_dst_before, n_after, eic_dst_after, dW])
        print("e{}= {:12.5g} e{}'= {:12.5g} dW={:10.8g} n={:8.5g}"
              " n'={:8.5g}".format(i, eic_dst_before,
                                   i, eic_dst_after,
                                   dW, n_before, n_after))

        n_before = n_after
        before_dir = after_dir
        z_dir_before = z_dir_after

    P, P1k, Ps = calc_path_length(eic)
    return eic, P