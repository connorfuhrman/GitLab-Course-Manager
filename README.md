# Gitlab Course Manager
The _Gitlab Course Manager_ (gcm) was created to manage a programming course which used GitLab's CI/CD pipeline as the course autograder. 
The project began at the University of Arizona in Fall 2020 when I moved the C++ programming course I taught away from ZyBooks (which had it's own autograder) and needed a way to autograde student submissions. 

## Under Construction
The repository is currently somewhat underdocumented as I've recently posted to GitHub and am working to generalize and improve the package.
This is still a work in progress but I'm hopeful that others may benefit from the capabilities and needs of others will drive further improvements. 
Contact connorfuhrman (at) email (dot) arizona (dot) edu with any questions. 


## Documentation
Source code documentation may be generated via Doxygen. The below subsections describe concepts. 

### Settings
GCM relies on an [INI](https://en.wikipedia.org/wiki/INI_file) file for necessary configuration settings. An example INI file is shown below: 

```ini
TODO add file
```

However there is a function `_get_auth_info` which can be updated to use a different configuration format if that is required.

### GitLab Structure
GCM makes some fundamental assumptions about the layout of the course's GitLab groups. It's assumed that there is some group which holds subgroups corresponding to each student where each student group holds assignments for each student. E.g., 


```
ECE 275 FS 2021
	Individual Student Groups
		Alice Apple
		Bobby Brige
		Charlie Chimichanga
		...
```
		


<!--  LocalWords:  GCM INI GitLab
 -->
