"""Tests for generator.sites: where each site's objects live (ADR 0015)."""
import unittest

from generator import sites
from generator.points import DeviceRow


class SiteTargetTests(unittest.TestCase):
    def test_a_site_gateway_runs_its_own_site_in_its_default_provider(self):
        for site in ("site1", "site2"):
            self.assertEqual((sites.gateway_for(site), sites.provider_for(site)), (site, "default"))
            self.assertFalse(sites.is_oem(site))

    def test_an_oem_site_is_read_by_the_hub_in_a_provider_named_for_the_site(self):
        for site in sites.OEM_SITES:
            self.assertEqual((sites.gateway_for(site), sites.provider_for(site)), ("hub", site))
            self.assertTrue(sites.is_oem(site))

    def test_there_are_six_oem_sites_oem1_to_oem6(self):
        self.assertEqual(sites.OEM_SITES, ("oem1", "oem2", "oem3", "oem4", "oem5", "oem6"))


class ResourceNameTests(unittest.TestCase):
    def test_a_site_gateways_device_keeps_its_plain_name(self):
        self.assertEqual(sites.resource_name("site1", "Inv1"), "Inv1")

    def test_an_oem_devices_name_carries_the_site_because_device_names_are_unique_across_the_hub(self):
        self.assertEqual(sites.resource_name("oem1", "Inv1"), "oem1_Inv1")
        self.assertEqual(sites.resource_name("oem2", "Inv1"), "oem2_Inv1")

    def test_a_row_exposes_both_its_tag_name_and_its_device_name(self):
        row = DeviceRow("oem3", "Inv2", "inverter", 2, "oem3", 15020, 2000.0)
        self.assertEqual((row.device, row.resource_name), ("Inv2", "oem3_Inv2"))
        self.assertEqual(row.tag_path, "Inverters/Inv2")  # the path below [oem3], the same shape as every other site


if __name__ == "__main__":
    unittest.main()
