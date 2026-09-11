import unittest
from zqhj_search import StripSearch


class SearchTests(unittest.TestCase):
    def test_distinct_strips_inside_public_bounds(self):
        tracks=[]
        for uid in ('a','b','c'):
            s=StripSearch(uid);s.goal((0,0),(-2000,2000,-1500,1500),{'a','b','c'}-{uid})
            tracks.append({p[0] for p in s.points})
            self.assertTrue(all(-1750<=x<=1750 and -1250<=y<=1250 for x,y in s.points))
        self.assertFalse(tracks[0]&tracks[1]);self.assertFalse(tracks[1]&tracks[2]);self.assertFalse(tracks[0]&tracks[2])

    def test_radio_loss_does_not_reshuffle(self):
        s=StripSearch('b');s.goal((0,0),(-2000,2000,-1500,1500),{'a','c'})
        points=list(s.points);s.goal((0,0),(-2000,2000,-1500,1500),{})
        self.assertEqual(s.points,points)

    def test_reaches_and_reverses_route(self):
        s=StripSearch('a');s.goal((0,0),(-300,300,-300,300),{})
        for _ in range(len(s.points)):s.goal(s.points[s.index],(-300,300,-300,300),{})
        self.assertEqual(s.laps,1)


if __name__=='__main__':unittest.main()
