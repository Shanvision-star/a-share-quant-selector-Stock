import unittest

from web.backend.services.stock_list_service import paginate_codes


class StockListServiceTest(unittest.TestCase):
    def test_paginate_codes_respects_page_and_size(self):
        codes = [f"{i:06d}" for i in range(1, 21)]
        page_codes, total = paginate_codes(codes, page=2, per_page=5)
        self.assertEqual(total, 20)
        self.assertEqual(page_codes, ["000006", "000007", "000008", "000009", "000010"])
