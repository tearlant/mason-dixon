# mason-dixon
## A library for optimally dividing maps

For a live demonstration of how the main algorithm works, please visit www.tearlant.com/mason-dixon

------------------------------------

## Running the demonstration locally

The demonstration should run out of the box in Python 3.10. To install all dependencies, at the command line, type
```
python -m pip install -r requirements.txt
```
Once the environment is properly set up, the demo should run on port 8888.

------------------------------------

Welcome to the prototype of MasonDixon.

In all fields of data visualization, many challenges stem from plots that are technically accurate but misleading. This algorithm specifically addresses one such challenge in geospatial data analysis.

When colouring a map according to a variable (for example, per capita income or the average cost of a hotel per region), it is not trivial to divide a map optimally. On the one hand, we do not want too many large regions without cities. Conversely, if too many cities or population centres are bunched into a single region, it can skew statistics and make the map misleading.

MasonDixon is a geographic engine that combines geospatial, mathematical, and statistical methods to divide maps in an intelligent way.

------------------------------------

To demonstrate the algorithm, a simple app has been built. The prototype is hosted at www.tearlant.com/mason-dixon

When the user is zooming and panning on a map, regions are automatically divided based on the current field of view. For simplicity, the app associates randomly generated data to a list of cities, and then colours the regions based on that data. This could easily be replaced with a numerical variable, such as the cost of the average hotel room in the region. (Most travel APIs do not offer this data for free, so I defer the creation of a travel app to the future).

The point should be clear though; as the user zooms and pans on the map, the algorithm divides the field of view into regions in such a way that there are not too many population centres in a single region of the map. The regions are then overlaid on the base map, and coloured based on the underlying data.

------------------------------------

The algorithm takes a list of (latitude, longitude) pairs, for example a list of global cities, hotels, offices, etc. A numerical value is applied to each entry in the list, and an aggregating function (usually linear regression or population-weighting) is used to determine the aggregate value for the region.

If the user clicks the "Update Data" button, the values in the database will be updated (just adding random perturbations to existing values), and the new values will propagate to the map. In particular, these values are updated asynchronously, so the update could be easily swapped out with any web API call. For example, MasonDixon could be used to build an app that dynamically scrapes the average fare to fly to an airport or the average price of a hotel room in a city.

As a side note, most base maps use WebMercator coordinates to properly render, but most commercial web APIs (for example for travel data) use WGS84 coordinates. As such, the server was designed to use WGS84 coordinates when retrieving data, and perform the appropriate calculations to convert back and forth to WebMercator when communicating with the low-level mathematical and mapping functions.

------------------------------------

## Citations and Key Packages

Natural Earth. Free vector and raster map data @ https://naturalearthdata.com
Bokeh: Python library for interactive visualization @ https://bokeh.org/
GeoPandas: Python tools for geographic data @ https://github.com/Geopandas/Geopandas
Tornado Web Server @ https://www.tornadoweb.org/
ColorCET: Good Colour Maps by Peter Kovesi @ https://colorcet.com/
