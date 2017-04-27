import re
from datetime import timedelta
from logging import getLevelName

import yaml
from boltons.timeutils import parse_timedelta
from typing import List, Iterable, Type, Dict, Any

from openstacktenantcleanup.detectors import PreventDeleteDetector, prevent_delete_protected_image_detector, \
    prevent_delete_image_in_use_detector, prevent_delete_key_pair_in_use_detector, created_exclude_detector, \
    create_delete_if_older_than_detector
from openstacktenantcleanup.external.hgicommon.models import Model
from openstacktenantcleanup.managers import OpenstackInstanceManager, Manager, OpenstackImageManager, \
    OpenstackKeyPairManager
from openstacktenantcleanup.models import OpenstackCredentials

_GENERAL_PROPERTY = "general"
_GENERAL_RUN_EVERY_PROPERTY = "run-every"
_GENERAL_LOG_PROPERTY = "log"
_GENERAL_LOG_LOCATION_PROPERTY = "location"
_GENERAL_LOG_LEVEL_PROPERTY = "level"
_CLEANUP_PROPERTY = "cleanup"
_CLEANUP_OPENSTACK_AUTH_URL_PROPERTY = "openstack_auth_url"
_CLEANUP_CREDENTIALS_PROPERTY = "credentials"
_CLEANUP_CREDENTIALS_USERNAME_PROPERTY = "username"
_CLEANUP_CREDENTIALS_PASSWORD_PROPERTY = "password"
_CLEANUP_TENANT_PROPERTY = "tenant"
_CLEANUP_INSTANCES_PROPERTY = "instances"
_CLEANUP_IMAGES_PROPERTY = "images"
_CLEANUP_KEY_PAIRS_PROPERTY = "key-pairs"
_CLEANUP_REMOVE_IF_OLDER_THAN_PROPERTY = "remove-if-older-than"
_CLEANUP_EXCLUDE_PROPERTY = "exclude"
_CLEANUP_REMOVE_ONLY_IF_UNUSED_PROPERTY = "remove-only-if-unused"


class CleanupAreaConfiguration(Model):
    """
    Configuration for how an area (e.g. images, key-pairs) is to be cleaned.
    """
    def __init__(self, prevent_delete_detectors: Iterable[PreventDeleteDetector]=None):
        self.prevent_delete_detectors = prevent_delete_detectors


class CleanupConfiguration(Model):
    """
    Configuration for how a set of areas are to be cleaned.
    """
    def __init__(self, credentials: List[OpenstackCredentials]=None):
        self.credentials = credentials if credentials is not None else []
        self.cleanup_areas: Dict[Type[Manager], CleanupAreaConfiguration] = {}


class LogConfiguration(Model):
    """
    Configuration for logging.
    """
    def __init__(self, location: str=None, level: int=None):
        self.location = location
        self.level = level


class GeneralConfiguration(Model):
    """
    General configuration.
    """
    def __init__(self, run_period: timedelta=None, log: LogConfiguration=None):
        self.run_period = run_period
        self.log = log


class Configuration(Model):
    """
    Full configuration.
    """
    def __init__(self, general_configuration: GeneralConfiguration, cleanup_configurations: List[CleanupConfiguration]):
        self.general_configuration = general_configuration
        self.cleanup_configurations = cleanup_configurations


def _create_common_prevent_delete_detectors(parent_property: Dict[str, Any]) -> List[PreventDeleteDetector]:
    """
    TODO
    :param parent_property: 
    :return: 
    """
    detectors: List[PreventDeleteDetector] = []

    if _CLEANUP_EXCLUDE_PROPERTY in parent_property:
        excludes = [re.compile(exclude) for exclude in parent_property[_CLEANUP_EXCLUDE_PROPERTY]]
        detectors.append(created_exclude_detector(excludes))

    if _CLEANUP_REMOVE_IF_OLDER_THAN_PROPERTY in parent_property:
        delete_if_older_than = parse_timedelta(parent_property[_CLEANUP_REMOVE_IF_OLDER_THAN_PROPERTY])
        detectors.append(create_delete_if_older_than_detector(delete_if_older_than))

    return detectors


def parse_configuration(location: str):
    """
    Parses the configuration in the given location.
    :param location: the location of the configuration that is to be parsed
    :return: parsed configuration
    """
    with open(location, "r") as file:
        raw_configuration = yaml.load(file)

    raw_general = raw_configuration[_GENERAL_PROPERTY]
    general_configuration = GeneralConfiguration(
        run_period=parse_timedelta(raw_general[_GENERAL_RUN_EVERY_PROPERTY]),
        log=LogConfiguration(
            location=raw_general[_GENERAL_LOG_PROPERTY][_GENERAL_LOG_LOCATION_PROPERTY],
            level=getLevelName(raw_general[_GENERAL_LOG_PROPERTY][_GENERAL_LOG_LEVEL_PROPERTY].upper())
        )
    )

    cleanup_configuration = CleanupConfiguration()
    for raw_cleanup in raw_configuration[_CLEANUP_PROPERTY]:
        raw_credentials = raw_cleanup[_CLEANUP_CREDENTIALS_PROPERTY]
        for raw_credential in raw_credentials:
            cleanup_configuration.credentials.append(OpenstackCredentials(
                auth_url=raw_cleanup[_CLEANUP_OPENSTACK_AUTH_URL_PROPERTY],
                tenant=raw_cleanup[_CLEANUP_TENANT_PROPERTY],
                username=raw_credential[_CLEANUP_CREDENTIALS_USERNAME_PROPERTY],
                password=raw_credential[_CLEANUP_CREDENTIALS_PASSWORD_PROPERTY],
            ))

        if _CLEANUP_IMAGES_PROPERTY in raw_cleanup:
            raw_images = raw_cleanup[_CLEANUP_IMAGES_PROPERTY]
            detectors = _create_common_prevent_delete_detectors(raw_images)
            detectors.append(prevent_delete_protected_image_detector)
            detectors.append(prevent_delete_image_in_use_detector)
            cleanup_configuration.cleanup_areas[OpenstackImageManager] = CleanupAreaConfiguration(detectors)
    
        if _CLEANUP_INSTANCES_PROPERTY in raw_cleanup:
            raw_instances = raw_cleanup[_CLEANUP_INSTANCES_PROPERTY]
            detectors = _create_common_prevent_delete_detectors(raw_instances)
            cleanup_configuration.cleanup_areas[OpenstackInstanceManager] = CleanupAreaConfiguration(detectors)

        if _CLEANUP_KEY_PAIRS_PROPERTY in raw_cleanup:
            raw_keypairs = raw_cleanup[_CLEANUP_KEY_PAIRS_PROPERTY]
            detectors = _create_common_prevent_delete_detectors(raw_keypairs)

            if raw_keypairs[_CLEANUP_REMOVE_ONLY_IF_UNUSED_PROPERTY]:
                detectors.append(prevent_delete_key_pair_in_use_detector)

            cleanup_configuration.cleanup_areas[OpenstackKeyPairManager] = CleanupAreaConfiguration(detectors)

    return Configuration(
        general_configuration=general_configuration,
        cleanup_configurations=[cleanup_configuration]
    )